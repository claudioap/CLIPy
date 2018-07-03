import logging
import re
from queue import Queue
from time import sleep
from threading import Lock

from .. import parser
from .. import database as db
from ..session import Session
from ..crawler import PageCrawler, crawl_class_turns, crawl_class_enrollments, crawl_classes, crawl_admissions
from ..database.candidates import InstitutionCandidate, DepartmentCandidate, CourseCandidate
from ..utils import parse_clean_request
from .. import urls

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)
THREADS = 6  # high number means "Murder CLIP!", take care


def populate_institutions(session: Session, database: db.Controller):
    """
    Finds new institutions and adds them to the database. This is mostly bootstrap code, not very useful later on.
    This is not thread-safe.

    :param session: Web session
    :param database: Database controller
    """
    found = []
    known = {60002: "Escola Nacional de Saúde Publica",
             109054: "Faculdade de Ciências Médicas",
             109055: "Faculdade de Ciências Sociais e Humanas",
             97747: "Faculdade de Ciências e Tecnologia",
             109056: "Faculdade de Direito",
             109057: "Faculdade de Economia (SBE)",
             60004: "Instituto de Higiene e Medicina Tropical",
             60003: "Instituto Superior de Estatística e Gestão da Informação",
             60005: "Instituto de Tecnologia Química e Biológica",
             97753: "Reitoria",
             113627: "Serviços de Ação Social"}
    hierarchy = parse_clean_request(session.get(urls.INSTITUTIONS))
    link_exp = re.compile('/?institui%E7%E3o=(\d+)$')
    for institution_link in hierarchy.find_all(href=link_exp):
        clip_id = int(link_exp.findall(institution_link.attrs['href'])[0])
        abbreviation = institution_link.text
        name = None if clip_id not in known else known[clip_id]
        institution = InstitutionCandidate(clip_id, name, abbreviation=abbreviation)
        found.append(institution)

    for institution in found:
        hierarchy = parse_clean_request(session.get(urls.INSTITUTION_YEARS.format(institution=institution.id)))
        year_exp = re.compile("\\b\d{4}\\b")
        institution_links = hierarchy.find_all(href=year_exp)
        for institution_link in institution_links:
            year = int(year_exp.findall(institution_link.attrs['href'])[0])
            institution.add_year(year)

    for institution in found:
        log.debug("Institution found: " + str(institution))

    database.add_institutions(found)


def populate_departments(session: Session, database: db.Controller):
    """
    Finds new departments and adds them to the database. *NOT* thread-safe.

    :param session: Web session
    :param database: Database controller
    """
    found = {}  # id -> Department
    for institution in database.get_institution_set():
        if not institution.has_time_range():  # if it has no time range to iterate through
            continue

        # Find the departments which existed each year
        for year in range(institution.first_year, institution.last_year + 1):
            log.info("Crawling departments of institution {}. Year:{}".format(institution, year))
            hierarchy = parse_clean_request(session.get(urls.DEPARTMENTS.format(
                institution=institution.internal_id, year=year)))
            for department_id, name in parser.get_departments(hierarchy):
                if department_id in found:  # update creation year
                    department = found[department_id]
                    if department.institution != institution:
                        raise Exception("Department {}({}) found in different institutions ({} and {})".format(
                            department.name, department_id, institution.internal_id, department.institution))
                    department.add_year(year)
                else:  # insert new
                    department = DepartmentCandidate(department_id, name, institution, year, year)
                    found[department_id] = department
    database.add_departments(found.values())


def populate_classes(session: Session, db_registry: db.SessionRegistry):
    """
    Finds new classes and adds them to the database
    :param session: Web session
    :param db_registry: Database session registry
    """
    database = db.Controller(db_registry)
    department_queue = Queue()
    [department_queue.put(department) for department in database.get_department_set()]
    department_lock = Lock()

    threads = []
    for thread in range(0, THREADS):
        threads.append(PageCrawler("Thread-" + str(thread),
                                   session, db_registry, department_queue, department_lock, crawl_classes))
        threads[thread].start()

    while True:
        department_lock.acquire()
        if department_queue.empty():
            department_lock.release()
            break
        else:
            log.info("{} departments remaining!".format(department_queue.qsize()))
            department_lock.release()
            sleep(5)

    for thread in threads:
        thread.join()


def populate_courses(session: Session, database: db.Controller):
    """
    Finds new courses and adds them to the database. *NOT* thread-safe.

    :param session: Web session
    :param database: Database controller
    """
    for institution in database.get_institution_set():
        courses = {}  # identifier -> Candidate pairs

        # Obtain couse id-name pairs from the course list page
        page = parse_clean_request(session.get(urls.COURSES.format(institution=institution.internal_id)))
        for identifier, name in parser.get_course_names(page):
            # Fetch the course curricular plan to find the activity years
            page = parse_clean_request(session.get(
                urls.CURRICULAR_PLANS.format(institution=institution.internal_id, course=identifier)))
            first, last = parser.get_course_activity_years(page)
            candidate = CourseCandidate(identifier, name, institution, first_year=first, last_year=last)
            courses[identifier] = candidate

        # fetch course abbreviation from the statistics page
        for degree in database.get_degree_set():
            page = parse_clean_request(session.get(urls.STATISTICS.format(
                institution=institution.internal_id, degree=degree.internal_id)))
            for identifier, abbreviation in parser.get_course_abbreviations(page):
                if identifier in courses:
                    courses[identifier].abbreviation = abbreviation
                    courses[identifier].degree = degree
                else:
                    raise Exception(
                        "{}({}) was listed in the abbreviation list but a corresponding course wasn't found".format(
                            abbreviation, identifier))

        database.add_courses(courses.values())


# populate student list from the national access contest (also obtain their preferences and current status)
def populate_nac_admissions(session: Session, db_registry: db.SessionRegistry):
    """
    Looks up the national access contest admission tables looking for new students and their current statuses.

    :param session: Web session
    :param db_registry: Database session registry
    """
    database = db.Controller(db_registry)
    # TODO rework the database to save states apart
    # TODO since the vast, VAST majority of clip students are from only one institution, change the implementation
    # to have threads crawling each year instead of each institution.
    # Since this only has to be run once at every trimester guess its not top priority

    institution_queue = Queue()
    for institution in database.get_institution_set():
        if not institution.has_time_range():  # if it has no time range to iterate through
            continue
        institution_queue.put(institution)

    institution_queue_lock = Lock()

    threads = []
    for thread in range(0, THREADS):
        threads.append(PageCrawler("Thread-" + str(thread),
                                   session, db_registry, institution_queue, institution_queue_lock, crawl_admissions))
        threads[thread].start()

    while True:
        institution_queue_lock.acquire()
        if institution_queue.empty():
            institution_queue_lock.release()
            break
        else:
            log.info("Approximately {} institutions remaining".format(institution_queue.qsize()))
            institution_queue_lock.release()
            sleep(5)

    for thread in threads:
        thread.join()


def populate_class_instances(session: Session, db_registry: db.SessionRegistry, year=None, period=None):
    """
    Finds student enrollments to class instances.
    TODO Make it lookup the every class instance static-ish data.

    :param session: Web session
    :param db_registry: Database session registry
    :param year: (Optional) Filter crawling to this year
    :param period: (Optional) Filter crawling to this period. Requires year to be set.
    """
    database = db.Controller(db_registry)
    class_instance_queue = Queue()
    if year is None:
        class_instances = database.fetch_class_instances()
    else:
        if period is None:
            class_instances = database.fetch_class_instances(year=year)
        else:
            class_instances = database.fetch_class_instances(year=year, period=period)
    [class_instance_queue.put(class_instance) for class_instance in class_instances]
    class_instances_lock = Lock()

    threads = []
    for thread in range(0, THREADS):
        threads.append(PageCrawler("Thread-" + str(thread), session, db_registry,
                                   class_instance_queue, class_instances_lock, crawl_class_enrollments))
        threads[thread].start()

    while True:
        class_instances_lock.acquire()
        if class_instance_queue.empty():
            class_instances_lock.release()
            break
        else:
            log.info("Approximately {} class instances remaining".format(class_instance_queue.qsize()))
            class_instances_lock.release()
            sleep(5)

    for thread in threads:
        thread.join()


def populate_class_instances_turns(session: Session, db_registry: db.SessionRegistry, year=None, period=None):
    """
    Finds class instance turns and updates their data if needed.

    :param session: Web session
    :param db_registry: Database session registry
    :param year: (Optional) Filter crawling to this year
    :param period: (Optional) Filter crawling to this period. Requires year to be set.
    """
    database = db.Controller(db_registry)
    class_instance_queue = Queue()
    if year is None:
        class_instances = database.fetch_class_instances()
    else:
        if period is None:
            class_instances = database.fetch_class_instances(year=year)
        else:
            class_instances = database.fetch_class_instances(year=year, period=period)
    [class_instance_queue.put(class_instance) for class_instance in class_instances]
    class_instances_lock = Lock()

    threads = []
    for thread in range(0, THREADS):
        threads.append(PageCrawler("Thread-" + str(thread), session, db_registry,
                                   class_instance_queue, class_instances_lock, crawl_class_turns))
        threads[thread].start()

    while True:
        class_instances_lock.acquire()
        if class_instance_queue.empty():
            class_instances_lock.release()
            break
        else:
            log.info("Approximately {} class instances remaining".format(class_instance_queue.qsize()))
            class_instances_lock.release()
            sleep(5)

    for thread in threads:
        thread.join()


def bootstrap_database(session: Session, db_registry: db.SessionRegistry):
    """
    | Bootstraps a database from scratch.
    | Can also be used as an updater but would be a waste of resources in most scenarios.
    | This is a very everything-intensive task. It uses a lot of CPU, DB IO and if I had to guess it also heats
      up the server by a few degrees.

    :param session: Web session
    :param db_registry: Database session registry
    """
    main_thread_db_controller = db.Controller(db_registry, cache=True)
    populate_institutions(session, main_thread_db_controller)  # 10 seconds
    populate_departments(session, main_thread_db_controller)  # 1-2 minutes
    populate_classes(session, db_registry)  # ~15 minutes
    populate_courses(session, main_thread_db_controller)  # ~5 minutes
    populate_nac_admissions(session, db_registry)  # ~30 minutes
    populate_class_instances(session, db_registry)  # ~4 hours
    populate_class_instances_turns(session, db_registry)  # ~16 Hours
