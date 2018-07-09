import logging
import traceback
from queue import Queue
from threading import Thread, Lock
from time import sleep

import re

from . import parser
from . import database as db
from .session import Session as WebSession
from . import urls
from .utils.utils import parse_clean_request

log = logging.getLogger(__name__)


class PageCrawler(Thread):
    def __init__(self, name, clip_session: WebSession, db_registry: db.SessionRegistry, work_queue: Queue,
                 queue_lock: Lock, crawl_function):
        Thread.__init__(self)
        self.name = name
        self.web_session: WebSession = clip_session
        self.db_registry = db_registry
        self.work_queue = work_queue
        self.queue_lock = queue_lock
        self.crawl_function = crawl_function

    def run(self):
        db_session = self.db_registry.get_session()
        db_controller = db.Controller(self.db_registry)
        while True:
            self.queue_lock.acquire()
            if not self.work_queue.empty():
                work_unit = self.work_queue.get()
                self.queue_lock.release()
                exception_count = 0
                while True:
                    try:
                        self.crawl_function(self.web_session, db_controller, work_unit)
                        exception_count = 0
                        break
                    except Exception:
                        db_session.rollback()
                        exception_count += 1
                        log.error(f'Failed to complete the job for the work unit with the ID {work_unit.id}.'
                                  f'Error: \n{traceback.format_exc()}\n'
                                  f'Retrying in {5 + min(exception_count, 55)} seconds...')

                    if exception_count > 10:
                        raise Exception("Thread {} failed for more than 10 times.")
                    sleep(5 + min(exception_count, 55))
            else:
                self.queue_lock.release()
                break

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.db_registry.remove()


def crawl_rooms(session: WebSession, database: db.Controller, institution: db.models.Institution):
    institution = database.session.merge(institution)
    rooms = {}  # id -> Candidate
    buildings = database.get_building_set()

    # for each year this institution operated (knowing that the first building was recorded in 2001)
    for year in range(max(2001, institution.first_year), institution.last_year + 1):
        for building in buildings:
            page = parse_clean_request(session.get(urls.BUILDING_SCHEDULE.format(
                institution=institution.id,
                building=building.id,
                year=year,
                period=1,
                period_type='s',
                weekday=2)))  # 2 is monday
            candidates = parser.get_places(page)
            if len(candidates) > 0:
                log.info(f'Found the following rooms in {building}, {year}:\n{candidates}')
            for identifier, room_type, name in candidates:
                candidate = db.candidates.Room(identifier=identifier, room_type=room_type, name=name, building=building)
                if identifier in rooms:
                    if rooms[identifier] != candidate:
                        raise Exception("Found two different rooms going by the same ID")
                else:
                    rooms[identifier] = candidate
    for room in rooms.values():
        database.add_room(room)


def crawl_teachers(session: WebSession, database: db.Controller, department: db.models.Department):
    department = database.session.merge(department)
    teachers = {}  # id -> Candidate
    periods = database.get_period_set()

    # for each year this institution operated (knowing that the first building was recorded in 2001)
    for year in range(department.first_year, department.last_year + 1):
        for period in periods:
            page = parse_clean_request(session.get(urls.DEPARTMENT_TEACHERS.format(
                institution=department.institution.id,
                department=department.id,
                year=year,
                period=period.part,
                period_type=period.letter)))
            candidates = parser.get_teachers(page)
            for identifier, name in candidates:
                # If there's a single teacher for a given period, a page with his/her schedule is served instead.
                # In those pages only the first match is the teacher, the second and so on aren't relevant.
                if name == 'Ficheiro':
                    break

                if identifier in teachers:
                    if teachers[identifier].name != name:
                        raise Exception(f'Found two teachers with the same id ({identifier}).\n'
                                        f'\tT1:"{teachers[identifier].name}"\n\tT2:{name}')
                else:
                    teachers[identifier] = db.candidates.Teacher(identifier=identifier, name=name)
    for candidate in teachers.values():
        database.add_teacher(candidate)


def crawl_classes(session: WebSession, database: db.Controller, department: db.models.Department):
    department = database.session.merge(department)
    classes = {}
    class_instances = []

    period_exp = re.compile('&tipo_de_per%EDodo_lectivo=(?P<type>\w)&per%EDodo_lectivo=(?P<stage>\d)$')
    abbr_exp = re.compile('\(.+\) .* \((?P<abbr>.+)\)')
    ects_exp = re.compile('(?P<ects>\d|\d.\d)\s?ECTS.*')

    # for each year this department operated
    for year in range(department.first_year, department.last_year + 1):
        page = parse_clean_request(session.get(urls.DEPARTMENT_PERIODS.format(
            institution=department.institution.id,
            department=department.id,
            year=year)))

        period_links = page.find_all(href=period_exp)

        # for each period this department teaches
        for period_link in period_links:
            match = period_exp.search(period_link.attrs['href'])
            period_type = match.group("type")
            part = int(match.group("stage"))
            if period_type == 'a':
                parts = 1
            elif period_type == 's':
                parts = 2
            elif period_type == 't':
                parts = 4
            else:
                parts = None

            period = database.get_period(part, parts)

            if period is None:
                raise Exception("Unknown period")

            period = database.get_period(part, parts)
            page = parse_clean_request(session.get(urls.DEPARTMENT_CLASSES.format(
                institution=department.institution.id,
                department=department.id,
                year=year,
                period=part,
                period_type=period_type)))

            class_links = page.find_all(href=urls.CLASS_EXP)

            # for each class in this period
            for class_link in class_links:
                class_id = int(urls.CLASS_EXP.findall(class_link.attrs['href'])[0])
                class_name = class_link.contents[0].strip()
                if class_id not in classes:
                    # Fetch abbreviation and number of ECTSs
                    page = parse_clean_request(session.get(urls.CLASS.format(
                        institution=department.institution.id,
                        year=year,
                        department=department.id,
                        period=part,
                        period_type=period_type,
                        class_id=class_id)))
                    elements = page.find_all('td', attrs={'class': 'subtitulo'})
                    abbr = None
                    ects = None
                    try:
                        abbr_matches = abbr_exp.search(elements[0].text)
                        abbr = str(abbr_matches.group('abbr')).strip()
                    except:
                        log.warning(f'Class {class_name}({class_id}) has no abbreviation')

                    try:
                        ects_matches = ects_exp.search(elements[1].text)
                        ects_s = str(ects_matches.group('ects')).strip()
                        # ECTSs are stored in halves. Someone decided it would be cool to award half ECTS...
                        ects = int(float(ects_s) * 2)
                    except:
                        log.warning(f'Class {class_name}({class_id}) has no ECTS information')

                    classes[class_id] = database.add_class(
                        db.candidates.Class(class_id, class_name, department, abbr, ects))

                if classes[class_id] is None:
                    raise Exception("Null class")
                class_instances.append(db.candidates.ClassInstance(classes[class_id], period, year))
    database.add_class_instances(class_instances)


def crawl_admissions(session: WebSession, database: db.Controller, institution: db.models.Institution):
    institution = database.session.merge(institution)
    admissions = []
    years = range(institution.first_year, institution.last_year + 1)
    for year in years:
        course_ids = set()  # Courses found in this year's page
        page = parse_clean_request(  # Fetch the page
            session.get(urls.ADMISSIONS.format(institution=institution.id, year=year)))
        course_links = page.find_all(href=urls.COURSE_EXP)
        for course_link in course_links:  # For every found course
            course_id = int(urls.COURSE_EXP.findall(course_link.attrs['href'])[0])
            course_ids.add(course_id)

        for course_id in course_ids:
            course = database.get_course(identifier=course_id)  # TODO ensure that doesn't end up as None
            for phase in range(1, 4):  # For every of the three phases
                page = parse_clean_request(session.get(urls.ADMITTED.format(
                    institution=institution.id,
                    year=year,
                    course=course_id,
                    phase=phase)))
                candidates = parser.get_admissions(page)
                for name, option, student_iid, state in candidates:
                    student = None
                    if student_iid:  # if the student has an id add him/her to the database
                        student = database.add_student(db.candidates.Student(student_iid, name, course, institution))

                    name = name if student is None else None
                    admission = db.candidates.Admission(student, name, course, phase, year, option, state)
                    admissions.append(admission)
    database.add_admissions(admissions)


def crawl_class_enrollments(session: WebSession, database: db.Controller, class_instance: db.models.ClassInstance):
    log.info("Crawling class instance ID %s" % class_instance.id)
    class_instance = database.session.merge(class_instance)
    institution = class_instance.parent.department.institution

    page = parse_clean_request(session.get(urls.CLASS_ENROLLED.format(
        institution=institution.id,
        department=class_instance.parent.department.id,
        year=class_instance.year,
        period=class_instance.period.part,
        period_type=class_instance.period.letter,
        class_id=class_instance.parent.internal_id)))

    # Strip file header and split it into lines
    if len(page.find_all(string=re.compile("Pedido inválido"))) > 0:
        log.debug("Instance skipped")
        return

    enrollments = []
    for student_id, name, abbreviation, statutes, course_abbr, attempt, student_year in parser.get_enrollments(page):
        course = database.get_course(abbreviation=course_abbr, year=class_instance.year)

        # TODO consider sub-courses EG: MIEA/[Something]
        observation = course_abbr if course is not None else (course_abbr + "(Unknown)")
        # update student info and take id
        student = database.add_student(db.candidates.Student(
            student_id, name, abbreviation=abbreviation, course=course, institution=institution))

        enrollment = db.candidates.Enrollment(student, class_instance, attempt, student_year, statutes, observation)
        enrollments.append(enrollment)

    database.add_enrollments(enrollments)


def crawl_class_info(session: WebSession, database: db.Controller, class_instance: db.models.ClassInstance):
    log.info("Crawling class instance ID %s" % class_instance.id)
    class_instance = database.session.merge(class_instance)
    institution = class_instance.parent.department.institution
    class_info = {}
    page = parse_clean_request(session.get(urls.CLASS_DESCRIPTION.format(
        institution=institution.id,
        department=class_instance.parent.department.id,
        year=class_instance.year,
        period=class_instance.period.part,
        period_type=class_instance.period.letter,
        class_id=class_instance.parent.internal_id)))
    class_info['description'], _ = parser.get_bilingual_info(page)
    page = parse_clean_request(session.get(urls.CLASS_OBJECTIVES.format(
        institution=institution.id,
        department=class_instance.parent.department.id,
        year=class_instance.year,
        period=class_instance.period.part,
        period_type=class_instance.period.letter,
        class_id=class_instance.parent.internal_id)))
    class_info['objectives'], _ = parser.get_bilingual_info(page)
    page = parse_clean_request(session.get(urls.CLASS_REQUIREMENTS.format(
        institution=institution.id,
        department=class_instance.parent.department.id,
        year=class_instance.year,
        period=class_instance.period.part,
        period_type=class_instance.period.letter,
        class_id=class_instance.parent.internal_id)))
    class_info['requirements'], _ = parser.get_bilingual_info(page)
    page = parse_clean_request(session.get(urls.CLASS_COMPETENCES.format(
        institution=institution.id,
        department=class_instance.parent.department.id,
        year=class_instance.year,
        period=class_instance.period.part,
        period_type=class_instance.period.letter,
        class_id=class_instance.parent.internal_id)))
    class_info['competences'], _ = parser.get_bilingual_info(page)
    page = parse_clean_request(session.get(urls.CLASS_PROGRAM.format(
        institution=institution.id,
        department=class_instance.parent.department.id,
        year=class_instance.year,
        period=class_instance.period.part,
        period_type=class_instance.period.letter,
        class_id=class_instance.parent.internal_id)))
    class_info['program'], _ = parser.get_bilingual_info(page)
    page = parse_clean_request(session.get(urls.CLASS_BIBLIOGRAPHY.format(
        institution=institution.id,
        department=class_instance.parent.department.id,
        year=class_instance.year,
        period=class_instance.period.part,
        period_type=class_instance.period.letter,
        class_id=class_instance.parent.internal_id)))
    class_info['bibliography'], _ = parser.get_bilingual_info(page)
    page = parse_clean_request(session.get(urls.CLASS_ASSISTANCE.format(
        institution=institution.id,
        department=class_instance.parent.department.id,
        year=class_instance.year,
        period=class_instance.period.part,
        period_type=class_instance.period.letter,
        class_id=class_instance.parent.internal_id)))
    class_info['assistance'], _ = parser.get_bilingual_info(page)
    page = parse_clean_request(session.get(urls.CLASS_TEACHING_METHODS.format(
        institution=institution.id,
        department=class_instance.parent.department.id,
        year=class_instance.year,
        period=class_instance.period.part,
        period_type=class_instance.period.letter,
        class_id=class_instance.parent.internal_id)))
    class_info['teaching_methods'], _ = parser.get_bilingual_info(page)
    page = parse_clean_request(session.get(urls.CLASS_EVALUATION_METHODS.format(
        institution=institution.id,
        department=class_instance.parent.department.id,
        year=class_instance.year,
        period=class_instance.period.part,
        period_type=class_instance.period.letter,
        class_id=class_instance.parent.internal_id)))
    class_info['evaluation_methods'], _ = parser.get_bilingual_info(page)
    page = parse_clean_request(session.get(urls.CLASS_EXTRA.format(
        institution=institution.id,
        department=class_instance.parent.department.id,
        year=class_instance.year,
        period=class_instance.period.part,
        period_type=class_instance.period.letter,
        class_id=class_instance.parent.internal_id)))
    class_info['extra_info'], _ = parser.get_bilingual_info(page)
    database.update_class_instance_info(class_instance, class_info)


def crawl_class_turns(session: WebSession, database: db.Controller, class_instance: db.models.ClassInstance):
    """
    Updates information on turns belonging to a given class instance.
    :param session: Browsing session
    :param database: Database controller
    :param class_instance: ClassInstance object to look after
    """
    log.info("Crawling class instance ID %s" % class_instance.id)
    class_instance = database.session.merge(class_instance)
    institution = class_instance.parent.department.institution

    # --- Prepare the list of turns to crawl ---
    page = parse_clean_request(session.get(urls.CLASS_TURNS.format(
        institution=institution.id,
        year=class_instance.year,
        department=class_instance.parent.department.id,
        class_id=class_instance.parent.internal_id,
        period=class_instance.period.part,
        period_type=class_instance.period.letter)))

    # When there is only one turn, the received page is the turn itself. (CLASS_TURN instead of CLASS_TURNS)
    single_turn = False
    turn_count = 0  # consistency check

    turn_type = None
    turn_number = None

    turn_links = page.find_all(href=urls.TURN_LINK_EXP)
    for turn_link in turn_links:
        if "aux=ficheiro" in turn_link.attrs['href'].lower():
            # there are no file links in turn lists, but they do exist on turn pages
            single_turn = True
        else:
            turn_count += 1
            turn_link_matches = urls.TURN_LINK_EXP.search(turn_link.attrs['href'])
            turn_type = turn_link_matches.group("type")
            turn_number = int(turn_link_matches.group("number"))

    turn_pages = []  # pages for turn parsing
    if single_turn:  # if the loaded page is the only turn
        if turn_count > 1:
            raise Exception("Class instance though to have one single turn now has many!")
        if turn_count == 0:
            log.warning("Turn page without any turn. Skipping")
            return
        turn_pages.append((page, turn_type, turn_number))  # save it, avoid requesting it again
    else:  # if there are multiple turns then request them
        for turn_link in turn_links:
            turn_page = parse_clean_request(session.get(urls.ROOT + turn_link.attrs['href']))
            turn_link_matches = urls.TURN_LINK_EXP.search(turn_link.attrs['href'])
            turn_type = turn_link_matches.group("type")
            turn_number = int(turn_link_matches.group("number"))
            turn_pages.append((turn_page, turn_type, turn_number))  # and save them with their metadata

    # --- Crawl found turns ---
    for page, turn_type, turn_number in turn_pages:  # for every turn in this class instance
        # Create turn
        instances, routes, teachers_names, restrictions, minutes, state, enrolled, capacity = parser.get_turn_info(page)
        routes_str = None  # TODO get rid of this pseudo-array after the curricular plans are done.
        for route in routes:
            if routes_str is None:
                routes_str = route
            else:
                routes_str += (';' + route)

        turn_type = database.get_turn_type(turn_type)
        teachers = []
        for name in teachers_names:
            teacher = database.get_teacher(name)
            if teacher is None:
                log.warning(f'Unknown teacher {name}')
            else:
                teachers.append(database.get_teacher(name))
        turn = database.add_turn(
            db.candidates.Turn(
                class_instance=class_instance,
                number=turn_number,
                turn_type=turn_type,
                enrolled=enrolled,
                capacity=capacity,
                minutes=minutes,
                routes=routes_str,
                restrictions=restrictions,
                state=state,
                teachers=teachers))

        # Create instances of this turn
        instances_aux = instances
        instances = []
        for weekday, start, end, building, room in instances_aux:
            if building:
                building = database.get_building(building)
                if room:
                    room = database.get_room(room, building)
            instances.append(db.candidates.TurnInstance(turn, start, end, weekday, room=room))
        del instances_aux
        database.add_turn_instances(instances)

        # Assign students to this turn
        students = []
        for name, student_id, abbreviation, course_abbreviation in parser.get_turn_students(page):
            course = database.get_course(abbreviation=course_abbreviation, year=class_instance.year)
            student = database.add_student(
                db.candidates.Student(student_id, name, course, institution, abbreviation=abbreviation))
            students.append(student)
        database.add_turn_students(turn, students)
