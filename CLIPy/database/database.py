import json
import logging
import os
import traceback
from typing import List

import sqlalchemy as sa
import sqlalchemy.orm as orm

from . import models, candidates

log = logging.getLogger(__name__)


def create_db_engine(backend: str, username=None, password=None, schema='CLIPy',
                     host='localhost', file=os.path.dirname(__file__) + '/CLIPy.db'):
    if backend == 'sqlite':
        log.debug(f"Establishing a database connection to file:'{file}'")
        return sa.create_engine(f"sqlite:///{file}?check_same_thread=False")  # , echo=True)
    elif backend == 'postgresql' and username is not None and password is not None and schema is not None:
        log.debug("Establishing a database connection to file:'{}'".format(file))
        return sa.create_engine(f"postgresql://{username}:{password}@{host}/{schema}")
    else:
        raise ValueError('Unsupported database backend or not enough arguments supplied')


class SessionRegistry:
    def __init__(self, engine: sa.engine.Engine):
        self.engine = engine
        self.factory = orm.sessionmaker(bind=engine)
        self.scoped_session = orm.scoped_session(self.factory)
        models.Base.metadata.create_all(engine)

    def get_session(self):
        return self.scoped_session()

    def remove(self):
        self.scoped_session.remove()


# NOT thread-safe. Each thread must instantiate its own controller from the registry.
class Controller:
    def __init__(self, database_registry: SessionRegistry, cache: bool = False):
        self.registry = database_registry
        self.session: orm.Session = database_registry.get_session()

        self.__caching__ = cache

        if self.session.query(models.Degree).count() == 0:
            self.__insert_default_degrees__()

        if self.session.query(models.Period).count() == 0:
            self.__insert_default_periods__()

        if self.session.query(models.TurnType).count() == 0:
            self.__insert_default_turn_types__()

        self.__weekdays__ = {'segunda': 0,
                             'terça': 1,
                             'terca': 1,
                             'quarta': 2,
                             'quinta': 3,
                             'sexta': 4,
                             'sábado': 5,
                             'sabado': 5,
                             'domingo': 6}
        if self.__caching__:
            self.__load_cached_collections__()

    def __load_cached_collections__(self):
        log.debug("Building cached collections")
        self.__load_institutions__()
        self.__load_degrees__()
        self.__load_periods__()
        self.__load_departments__()
        self.__load_courses__()
        self.__load_turn_types__()
        self.__load_teachers__()
        self.__load_buildings__()
        self.__load_rooms__()
        log.debug("Finished building cache")

    def __load_institutions__(self):
        log.debug("Building institution cache")
        institutions = {}
        for institution in self.session.query(models.Institution).all():
            institutions[institution.id] = institution
        self.__institutions__ = institutions

    def __load_degrees__(self):
        log.debug("Building degree cache")
        degrees = {}
        for degree in self.session.query(models.Degree).all():
            if degree.id == 4:  # FIXME, skipping the Integrated Master to avoid having it replace the Master
                continue
            degrees[degree.internal_id] = degree
        self.__degrees__ = degrees

    def __load_periods__(self):
        log.debug("Building period cache")
        periods = {}

        for period in self.session.query(models.Period).all():
            if period.parts not in periods:  # unseen letter
                periods[period.parts] = {}
            periods[period.parts][period.part] = period
        self.__periods__ = periods

    def __load_departments__(self):
        log.debug("Building department cache")
        departments = {}
        for department in self.session.query(models.Department).all():
            departments[department.id] = department
        self.__departments__ = departments

    def __load_courses__(self):
        log.debug("Building course cache")
        courses = {}
        course_abbreviations = {}
        for course in self.session.query(models.Course).all():
            courses[course.internal_id] = course

            if course.abbreviation not in course_abbreviations:
                course_abbreviations[course.abbreviation] = []
            course_abbreviations[course.abbreviation].append(course)
        self.__courses__ = courses
        self.__course_abbrs__ = course_abbreviations

    def __load_turn_types__(self):
        log.debug("Building turn types cache")
        turn_types = {}
        for turn_type in self.session.query(models.TurnType).all():
            turn_types[turn_type.abbreviation] = turn_type
        self.__turn_types__ = turn_types

    def __load_teachers__(self):
        log.debug("Building teacher cache")
        teachers = {}
        for teacher in self.session.query(models.Teacher).all():
            teachers[teacher.name] = teacher
        self.__teachers__ = teachers

    def __load_buildings__(self):
        log.debug("Building building cache")
        buildings = {}
        for building in self.session.query(models.Building).all():
            buildings[building.name] = building
        self.__buildings__ = buildings

    def __load_rooms__(self):
        log.debug("Building room cache")
        rooms = {}
        for room, building in self.session.query(models.Room, models.Building).all():
            if building.name not in rooms:
                rooms[building.name] = {}
            if room.room_type not in rooms[building.name]:
                rooms[building.name][room.room_type] = {}
            rooms[building.name][room.room_type][room.name] = building
        self.__rooms__ = rooms

    def __insert_default_periods__(self):
        self.session.add_all(
            [models.Period(id=1, part=1, parts=1, letter='a'),
             models.Period(id=2, part=1, parts=2, letter='s'),
             models.Period(id=3, part=2, parts=2, letter='s'),
             models.Period(id=4, part=1, parts=4, letter='t'),
             models.Period(id=5, part=2, parts=4, letter='t'),
             models.Period(id=6, part=3, parts=4, letter='t'),
             models.Period(id=7, part=4, parts=4, letter='t')])
        self.session.commit()

    def __insert_default_degrees__(self):
        self.session.add_all(
            [models.Degree(id=1, internal_id='L', name="Licenciatura"),
             models.Degree(id=2, internal_id='M', name="Mestrado"),
             models.Degree(id=3, internal_id='D', name="Doutoramento"),
             models.Degree(id=4, internal_id='M', name="Mestrado Integrado"),
             models.Degree(id=5, internal_id='Pg', name="Pos-Graduação"),
             models.Degree(id=6, internal_id='EA', name="Estudos Avançados"),
             models.Degree(id=7, internal_id='pG', name="Pré-Graduação")])
        self.session.commit()

    def __insert_default_turn_types__(self):
        self.session.add_all(
            [models.TurnType(id=1, name="Theoretical", abbreviation="t"),
             models.TurnType(id=2, name="Practical", abbreviation="p"),
             models.TurnType(id=3, name="Practical-Theoretical", abbreviation="tp"),
             models.TurnType(id=4, name="Seminar", abbreviation="s"),
             models.TurnType(id=5, name="Tutorial Orientation", abbreviation="ot")])
        self.session.commit()

    def get_institution(self, identifier: int):
        if self.__caching__:
            if identifier not in self.__institutions__:
                return None
            return self.__institutions__[identifier]
        else:
            return self.session.query(models.Institution).filter_by(id=identifier).first()

    def get_department(self, identifier: int):
        if self.__caching__:
            if identifier not in self.__departments__:
                return None
            return self.__departments__[identifier]
        else:
            return self.session.query(models.Department).filter_by(id=identifier).first()

    def get_degree(self, abbreviation: str):
        if self.__caching__:
            if abbreviation not in self.__degrees__:
                return None
            return self.__degrees__[abbreviation]
        else:
            return self.session.query(models.Degree).filter_by(id=abbreviation).first()

    def get_period(self, part: int, parts: int):
        if self.__caching__:
            if parts not in self.__periods__ or part > parts:
                return None
            try:
                return self.__periods__[parts][part]
            except KeyError:
                return None
        else:
            return self.session.query(models.Period).filter_by(part=part, parts=parts).first()

    def get_institution_set(self):
        if self.__caching__:
            return set(self.__institutions__.values())
        else:
            return set(self.session.query(models.Institution).all())

    def get_building_set(self):
        if self.__caching__:
            return set(self.__buildings__.values())
        else:
            return set(self.session.query(models.Building).all())

    def get_department_set(self):
        if self.__caching__:
            return set(self.__departments__.values())
        else:
            return set(self.session.query(models.Department).all())

    def get_degree_set(self):
        if self.__caching__:
            return set(self.__degrees__.values())
        else:
            return set(self.session.query(models.Degree).all())

    def get_period_set(self):
        return set(self.session.query(models.Period).all())

    def get_course(self, identifier=None, abbreviation=None, year=None):
        if identifier is not None:
            if self.__caching__:
                if identifier in self.__courses__:
                    return self.__courses__[identifier]
            else:
                return self.session.query(models.Course).filter_by(internal_id=identifier).first()
        elif abbreviation is not None:
            if self.__caching__:
                if abbreviation not in self.__course_abbrs__:
                    return None
                matches = self.__course_abbrs__[abbreviation]
                if len(matches) == 0:
                    return None
                elif len(matches) == 1:
                    return matches[0]
                else:
                    if year is None:
                        raise Exception("Multiple matches. Year unspecified")

                    for match in matches:
                        if match.initial_year <= year <= match.last_year:
                            return match
            else:
                matches = self.session.query(models.Course).filter_by(internal_id=identifier).all()
                if len(matches) == 0:
                    return None
                elif len(matches) == 1:
                    return matches[0]

                if year is None:
                    raise Exception("Multiple matches. Year unspecified")

                for match in matches:
                    if match.initial_year <= year <= match.last_year:
                        return match

    def get_turn_type(self, abbreviation: str):
        if self.__caching__:
            if abbreviation in self.__turn_types__:
                return self.__turn_types__[abbreviation]
        else:
            return self.session.query(models.TurnType).filter_by(abbreviation=abbreviation).first()

    def get_teacher(self, name: str, department: models.Department):
        if self.__caching__:
            if name in self.__teachers__:
                return self.__teachers__[name]
        else:
            matches = self.session.query(models.Teacher).filter_by(name=name, department=department).all()
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                raise Exception(f'Several teachers with the name {name}')

    def get_class(self, internal_id: int):
        return self.session.query(models.Class).filter_by(internal_id=internal_id).first()

    def add_institutions(self, institutions: [candidates.Institution]):
        """
        Adds institutions to the database. It updates then in case they already exist but details differ.

        :param institutions: An iterable collection of institution candidates
        """
        new_count = 0
        updated_count = 0
        try:
            for candidate in institutions:
                # Lookup for existing institutions matching the new candidate
                institution = None
                if self.__caching__:
                    if candidate.id in self.__institutions__:
                        institution = self.__institutions__[candidate.id]
                else:
                    institution = self.session.query(models.Institution).filter_by(id=candidate.id).first()

                if institution is None:  # Create a new institution
                    self.session.add(models.Institution(
                        id=candidate.id,
                        name=candidate.name,
                        abbreviation=candidate.abbreviation,
                        first_year=candidate.first_year,
                        last_year=candidate.last_year))
                    new_count += 1
                else:  # Update the existing one accordingly
                    updated = False
                    if candidate.name is not None and institution.name != candidate.name:
                        institution.name = candidate.name
                        updated = True

                    if candidate.abbreviation is not None:
                        institution.abbreviation = candidate.abbreviation
                        updated = True

                    if institution.first_year is None:
                        institution.first_year = candidate.first_year
                        updated = True
                    elif candidate.first_year is not None and candidate.first_year < institution.first_year:
                        institution.first_year = candidate.first_year
                        updated = True

                    if institution.last_year is None:
                        institution.last_year = candidate.last_year
                        updated = True
                    elif candidate.last_year is not None and candidate.last_year > institution.last_year:
                        institution.last_year = candidate.last_year
                        updated = True

                    if updated:
                        updated_count += 1

            self.session.commit()
            log.info(f"{new_count} institutions added and {updated_count} updated!")
            if self.__caching__:
                self.__load_institutions__()
        except Exception:
            log.error("Failed to add the institutions\n" + traceback.format_exc())
            self.session.rollback()

    def add_departments(self, departments: [candidates.Department]):
        """
        Adds departments to the database. It updates then in case they already exist but details differ.

        :param departments: An iterable collection of department candidates
        """
        new_count = 0
        updated_count = 0
        try:
            for candidate in departments:
                # Lookup for existing departments matching the new candidate
                department = None
                if self.__caching__:
                    if candidate.id in self.__departments__:
                        department = self.__departments__[candidate.id]
                else:
                    department = self.session.query(models.Department).filter_by(id=candidate.id).first()

                if department is None:  # Create a new department
                    self.session.add(models.Department(
                        id=candidate.id,
                        name=candidate.name,
                        first_year=candidate.first_year,
                        last_year=candidate.last_year,
                        institution=candidate.institution))
                    new_count += 1
                else:  # Update the existing one accordingly
                    updated = False
                    if candidate.name is not None and department.name != candidate.name:
                        department.name = candidate.name
                        updated = True

                    if department.first_year is None:
                        department.first_year = candidate.first_year
                        updated = True
                    elif candidate.first_year is not None and candidate.first_year < department.first_year:
                        department.first_year = candidate.first_year
                        updated = True

                    if department.last_year is None:
                        department.last_year = candidate.last_year
                        updated = True
                    elif candidate.last_year is not None and candidate.last_year > department.last_year:
                        department.last_year = candidate.last_year
                        updated = True

                    if updated:
                        updated_count += 1

            log.info(f"{new_count} departments added and {updated_count} updated!")
            self.session.commit()
            if self.__caching__:
                self.__load_departments__()
        except Exception:
            log.error("Failed to add the departments\n" + traceback.format_exc())
            self.session.rollback()

    def add_class(self, candidate: candidates.Class):
        db_class = self.session.query(models.Class).filter_by(
            internal_id=candidate.id,
            department=candidate.department
        ).first()

        if db_class is not None:  # Already stored
            if db_class.name != candidate.name:
                raise Exception("Class name change attempt. {} to {} (iid {})".format(
                    db_class.name, candidate.name, candidate.id))

            if candidate.abbreviation is not None:
                if db_class.abbreviation is None:
                    db_class.abbreviation = candidate.abbreviation
                    self.session.commit()
                    return db_class

                if db_class.abbreviation is not None and db_class.abbreviation != candidate.abbreviation:
                    raise Exception("Class abbreviation change attempt. {} to {} (iid {})".format(
                        db_class.abbreviation, candidate.abbreviation, candidate.id))

            return db_class

        log.info("Adding class {}".format(candidate))
        db_class = models.Class(
            internal_id=candidate.id,
            name=candidate.name,
            department=candidate.department,
            abbreviation=candidate.abbreviation,
            ects=candidate.ects)
        self.session.add(db_class)
        self.session.commit()
        return db_class

    def add_class_instances(self, instances: [candidates.ClassInstance]):
        ignored = 0
        for instance in instances:
            db_class_instance = self.session.query(models.ClassInstance).filter_by(
                parent=instance.parent,
                year=instance.year,
                period=instance.period
            ).first()
            if db_class_instance is not None:
                ignored += 1
            else:
                self.session.add(models.ClassInstance(
                    parent=instance.parent,
                    year=instance.year,
                    period=instance.period
                ))
                self.session.commit()
        if len(instances) > 0:
            log.info("{} class instances added successfully! ({} ignored)".format(len(instances), ignored))

    def update_class_instance_info(self, instance: models.ClassInstance, info):
        if 'description' in info:
            instance.description_pt = info['description'][0]
            instance.description_en = info['description'][1]
            instance.description_edited_datetime = info['description'][2]
            instance.description_editor = info['description'][3]
        if 'objectives' in info:
            instance.objectives_pt = info['objectives'][0]
            instance.objectives_en = info['objectives'][1]
            instance.objectives_edited_datetime = info['objectives'][2]
            instance.objectives_editor = info['objectives'][3]
        if 'requirements' in info:
            instance.requirements_pt = info['requirements'][0]
            instance.requirements_en = info['requirements'][1]
            instance.requirements_edited_datetime = info['requirements'][2]
            instance.requirements_editor = info['requirements'][3]
        if 'competences' in info:
            instance.competences_pt = info['competences'][0]
            instance.competences_en = info['competences'][1]
            instance.competences_edited_datetime = info['competences'][2]
            instance.competences_editor = info['competences'][3]
        if 'program' in info:
            instance.program_pt = info['program'][0]
            instance.program_en = info['program'][1]
            instance.program_edited_datetime = info['program'][2]
            instance.program_editor = info['program'][3]
        if 'bibliography' in info:
            instance.bibliography_pt = info['bibliography'][0]
            instance.bibliography_en = info['bibliography'][1]
            instance.bibliography_edited_datetime = info['bibliography'][2]
            instance.bibliography_editor = info['bibliography'][3]
        if 'assistance' in info:
            instance.assistance_pt = info['assistance'][0]
            instance.assistance_en = info['assistance'][1]
            instance.assistance_edited_datetime = info['assistance'][2]
            instance.assistance_editor = info['assistance'][3]
        if 'teaching_methods' in info:
            instance.teaching_methods_pt = info['teaching_methods'][0]
            instance.teaching_methods_en = info['teaching_methods'][1]
            instance.teaching_methods_edited_datetime = info['teaching_methods'][2]
            instance.teaching_methods_editor = info['teaching_methods'][3]
        if 'evaluation_methods' in info:
            instance.evaluation_methods_pt = info['evaluation_methods'][0]
            instance.evaluation_methods_en = info['evaluation_methods'][1]
            instance.evaluation_methods_edited_datetime = info['evaluation_methods'][2]
            instance.evaluation_methods_editor = info['evaluation_methods'][3]
        if 'extra_info' in info:
            instance.extra_info_pt = info['extra_info'][0]
            instance.extra_info_en = info['extra_info'][1]
            instance.extra_info_edited_datetime = info['extra_info'][2]
            instance.extra_info_editor = info['extra_info'][3]
        if 'working_hours' in info:
            instance.working_hours = json.dumps(info['working_hours'])

        self.session.commit()

    def add_courses(self, courses: [candidates.Course]):
        updated = 0
        try:
            for course in courses:
                db_course = self.session.query(models.Course).filter_by(
                    internal_id=course.id,
                    institution=course.institution
                ).first()

                if db_course is None:
                    self.session.add(models.Course(
                        internal_id=course.id,
                        name=course.name,
                        abbreviation=course.abbreviation,
                        first_year=course.first_year,
                        last_year=course.last_year,
                        degree=course.degree,
                        institution=course.institution))
                    self.session.commit()
                else:
                    updated += 1
                    changed = False
                    if course.name is not None and course.name != db_course.name:
                        raise Exception("Attempted to change a course name")

                    if course.abbreviation is not None:
                        db_course.abbreviation = course.abbreviation
                        changed = True
                    if course.degree is not None:
                        db_course.degree = course.degree
                        changed = True
                    if db_course.first_year is None \
                            or course.first_year is not None and course.first_year < db_course.first_year:
                        db_course.first_year = course.first_year
                        changed = True
                    if db_course.last_year is None \
                            or course.last_year is not None and course.last_year < db_course.last_year:
                        db_course.last_year = course.last_year
                        changed = True
                    if changed:
                        self.session.commit()

            if len(courses) > 0:
                log.info("{} courses added successfully! ({} updated)".format(len(courses), updated))
        except Exception:
            self.session.rollback()
            raise Exception("Failed to add courses.\n%s" % traceback.format_exc())
        finally:
            if self.__caching__:
                self.__load_courses__()

    def add_student(self, student: candidates.Student):
        if student.name is None or student.name == '':  # TODO Move this out of here
            raise Exception("Invalid name")

        if student.id is None:
            raise Exception('No student ID provided')

        if student.course is not None:
            # Search for institution instead of course since a transfer could have happened
            institution = student.course.institution
        elif student.institution is not None:
            institution = student.institution
        else:
            raise Exception("Neither course nor institution provided")

        db_students: List[models.Student] = self.session.query(models.Student).filter_by(internal_id=student.id).all()

        if len(db_students) == 0:  # new student, add him
            db_student = models.Student(
                internal_id=student.id,
                name=student.name,
                abbreviation=student.abbreviation,
                institution=institution,
                course=student.course)
            self.session.add(db_student)
            self.session.commit()
        elif len(db_students) == 1:
            db_student = db_students[0]
            if db_student.abbreviation == student.abbreviation or db_student.name == student.name:
                if db_student.abbreviation is None:
                    if student.abbreviation is not None:
                        db_student.abbreviation = student.abbreviation
                        self.session.commit()
                elif student.abbreviation is not None and student.abbreviation != db_student.abbreviation:
                    raise Exception(
                        "Attempted to change the student abbreviation to another one\n"
                        "Student:{}\n"
                        "Candidate{}".format(db_student, student))

                if student.course is not None:
                    db_student.course = student.course
                    self.session.commit()
            else:
                db_student = models.Student(
                    internal_id=student.id,
                    name=student.name,
                    abbreviation=student.abbreviation,
                    institution=institution,
                    course=student.course)
                self.session.add(db_student)

        else:  # database inconsistency
            students = ""
            for student in db_students:
                students += ("%s," % student)
            raise Exception("Duplicated students found:\n{}".format(students))
        return db_student

    def add_teacher(self, candidate: candidates.Teacher) -> models.Teacher:
        teacher = self.session.query(models.Teacher).filter_by(id=candidate.id,
                                                               name=candidate.name,
                                                               department=candidate.department).first()

        if teacher is None:
            teacher = models.Teacher(id=candidate.id, name=candidate.name, department=candidate.department)
            self.session.add(teacher)
            self.session.commit()
            if self.__caching__:
                self.__load_teachers__()

        return teacher

    def add_turn(self, turn: candidates.Turn) -> models.Turn:
        db_turn: models.Turn = self.session.query(models.Turn).filter_by(
            number=turn.number,
            class_instance=turn.class_instance,
            type=turn.type
        ).first()

        if db_turn is None:
            db_turn = models.Turn(
                class_instance=turn.class_instance,
                number=turn.number,
                type=turn.type,
                enrolled=turn.enrolled,
                capacity=turn.capacity,
                minutes=turn.minutes,
                routes=turn.routes,
                restrictions=turn.restrictions,
                state=turn.restrictions)
            self.session.add(db_turn)
            self.session.commit()
        else:
            changed = False
            if turn.minutes is not None and turn.minutes != 0:
                db_turn.minutes = turn.minutes
                changed = True
            if turn.enrolled is not None:
                db_turn.enrolled = turn.enrolled
                changed = True
            if turn.capacity is not None:
                db_turn.capacity = turn.capacity
                changed = True
            if turn.minutes is not None and turn.minutes != 0:
                db_turn.minutes = turn.minutes
                changed = True
            if turn.routes is not None:
                db_turn.routes = turn.routes
                changed = True
            if turn.restrictions is not None:
                db_turn.restrictions = turn.restrictions
                changed = True
            if turn.state is not None:
                db_turn.state = turn.state
                changed = True
            if changed:
                self.session.commit()

        [db_turn.teachers.append(teacher) for teacher in turn.teachers]
        return db_turn

    # Reconstructs the instances of a turn.
    # Destructive is faster because it doesn't worry about checking instance by instance,
    # it'll delete em' all and rebuilds
    def add_turn_instances(self, instances: List[candidates.TurnInstance], destructive=False):
        turn = None
        for instance in instances:
            if turn is None:
                turn = instance.turn
            elif turn != instance.turn:
                raise Exception('Instances belong to multiple turns')
        if turn is None:
            return

        if destructive:
            try:
                deleted = self.session.query(models.TurnInstance).filter_by(turn=turn).delete()
                if deleted > 0:
                    log.info(f"Deleted {deleted} turn instances from the turn {turn}")
            except Exception:
                self.session.rollback()
                raise Exception("Error deleting turn instances for turn {}\n{}".format(turn, traceback.format_exc()))

            for instance in instances:
                turn.instances.append(models.TurnInstance(
                    turn=turn,
                    start=instance.start,
                    end=instance.end,
                    room=instance.room,
                    weekday=instance.weekday))

            if len(instances) > 0:
                log.info(f"Added {len(instances)} turn instances to the turn {turn}")
                self.session.commit()
        else:
            db_turn_instances = self.session.query(models.TurnInstance).filter_by(turn=turn).all()
            for db_turn_instance in db_turn_instances:
                matched = False
                for instance in instances[:]:
                    if db_turn_instance.start == instance.start and db_turn_instance.end == instance.end and \
                            db_turn_instance.weekday == instance.weekday:
                        matched = True
                        if db_turn_instance.room != instance.room:  # Update the room
                            log.info(f'An instance of {turn} changed the room from '
                                     f'{db_turn_instance.room} to {instance.room}')
                            db_turn_instance.room = instance.room
                        instances.remove(instance)
                        break
                if not matched:
                    log.info(f'An instance of {turn} ceased to exist ({db_turn_instance})')
                    self.session.delete(db_turn_instance)
            for instance in instances:
                turn.instances.append(
                    models.TurnInstance(
                        turn=turn,
                        start=instance.start,
                        end=instance.end,
                        room=instance.room,
                        weekday=instance.weekday))

    def add_turn_students(self, turn: models.Turn, students: [candidates.Student]):
        [turn.students.append(student) for student in students]
        if len(students) > 0:
            self.session.commit()
            log.info("{} students added successfully to the turn {}!".format(len(students), turn))

    def add_admissions(self, admissions: [candidates.Admission]):
        admissions = list(map(lambda admission: models.Admission(
            student=admission.student,
            name=admission.name,
            course=admission.course,
            phase=admission.phase,
            year=admission.year,
            option=admission.option,
            state=admission.state
        ), admissions))
        self.session.add_all(admissions)

        if len(admissions) > 0:
            self.session.commit()
            log.info("{} admissions added successfully!".format(len(admissions)))

    def add_enrollments(self, enrollments: [candidates.Enrollment]):
        added = 0
        updated = 0
        for enrollment in enrollments:
            db_enrollment: models.Enrollment = self.session.query(models.Enrollment).filter_by(
                student=enrollment.student,
                class_instance=enrollment.class_instance
            ).first()
            if db_enrollment:
                changed = False
                if db_enrollment.observation is None and enrollment.observation is not None:
                    db_enrollment.observation = enrollment.observation
                    changed = True
                if db_enrollment.student_year is None and enrollment.student_year is not None:
                    db_enrollment.student_year = enrollment.student_year
                    changed = True
                if db_enrollment.attempt is None and enrollment.attempt is not None:
                    db_enrollment.attempt = enrollment.attempt
                    changed = True
                if db_enrollment.statutes is None and enrollment.statutes is not None:
                    db_enrollment.statutes = enrollment.statutes
                    changed = True
                if changed:
                    updated += 1
                    self.session.commit()
            else:
                enrollment = models.Enrollment(
                    student=enrollment.student,
                    class_instance=enrollment.class_instance,
                    attempt=enrollment.attempt,
                    student_year=enrollment.student_year,
                    statutes=enrollment.statutes,
                    observation=enrollment.observation)
                added += 1
                self.session.add(enrollment)
                self.session.commit()

        log.info("{} enrollments added and {} updated ({} ignored)!".format(
            added, updated, len(enrollments) - added - updated))

    def add_room(self, candidate: candidates.Room) -> models.Room:
        reload_cache = False
        try:
            if self.__caching__:
                if candidate.building in self.__rooms__ \
                        and candidate.type in self.__rooms__[candidate.building] \
                        and candidate.name in self.__rooms__[candidate.building][candidate.type]:
                    room = self.__rooms__[candidate.building][candidate.type][candidate.name]
                else:
                    room = models.Room(id=candidate.id,
                                       name=candidate.name,
                                       room_type=candidate.type,
                                       building=candidate.building)
                    self.session.add(room)
                    self.session.commit()
                    reload_cache = True
                return room
            else:
                room = self.session.query(models.Room).filter_by(
                    name=candidate.name, room_type=candidate.type, building=candidate.building).first()
                if room is None:
                    room = models.Room(id=candidate.id,
                                       name=candidate.name,
                                       room_type=candidate.type,
                                       building=candidate.building)
                    self.session.add(room)
                    self.session.commit()
                return room
        except Exception:
            log.error("Failed to add the room\n%s" % traceback.format_exc())
            self.session.rollback()
        finally:
            if self.__caching__ and reload_cache:
                self.__load_rooms__()

    def get_room(self, name: str, building: models.Building, room_type: models.RoomType = None) -> models.Room:
        if self.__caching__:
            if room_type:
                if building in self.__rooms__ and room_type in self.__rooms__[building] \
                        and name in self.__rooms__[building][room_type]:
                    return self.__rooms__[building][room_type][name]
            else:
                if building in self.__rooms__:
                    matches = []
                    for building_room_type in self.__rooms__[building]:
                        if name in building_room_type:
                            matches.append(building_room_type[name])
                    if len(matches) == 1:
                        return matches[0]
                    if len(matches) > 1:
                        raise Exception("Unable to determine which room is the correct one")
                raise Exception('Unknown building')
        else:
            if room_type:
                return self.session.query(models.Room).filter_by(name=name,
                                                                 room_type=room_type,
                                                                 building=building).first()
            else:
                matches = self.session.query(models.Room).filter_by(name=name, building=building).all()
                if len(matches) == 1:
                    return matches[0]
                else:
                    raise Exception("Unable to determine which room is the correct one")

    def add_building(self, building: candidates.Building) -> models.Building:
        if self.__caching__:
            if building.name in self.__buildings__:
                return self.__buildings__[building.name]
            try:
                building = models.Building(id=building.id, name=building.name)
                self.session.add(building)
                self.session.commit()
                return building
            except Exception:
                log.error("Failed to add the building\n%s" % traceback.format_exc())
                self.session.rollback()
            finally:
                if self.__caching__:
                    self.__load_buildings__()
        else:
            db_building = self.session.query(models.Building).filter_by(name=building.name).first()
            if db_building is None:
                db_building = models.Building(id=building.id, name=building.name)
                self.session.add(db_building)
                self.session.commit()
            return db_building

    def get_building(self, building: str) -> models.Building:
        if self.__caching__:
            if building in self.__buildings__:
                return self.__buildings__[building]
        else:
            return self.session.query(models.Building).filter_by(name=building).first()

    def fetch_class_instances(self, year_asc=True, year=None, period=None) -> [models.ClassInstance]:
        order = sa.asc(models.ClassInstance.year) if year_asc else sa.desc(models.ClassInstance.year)
        if year is None:
            if period is not None:
                log.warning("Period specified without an year")
            if year_asc:
                instances = self.session.query(models.ClassInstance).order_by(order).all()
            else:
                instances = self.session.query(models.ClassInstance).order_by(order).all()
        else:
            if period is None:
                instances = self.session.query(models.ClassInstance).filter_by(year=year).order_by(order).all()
            else:
                instances = self.session.query(models.ClassInstance). \
                    filter_by(year=year, period=period).order_by(order).all()
        return list(instances)

    def find_student(self, name: str, course=None):
        query_string = '%'
        for word in name.split():
            query_string += (word + '%')

        if course is None:
            return self.session.query(models.Student).filter(models.Student.name.ilike(query_string)).all()
        else:
            return self.session.query(models.Student).filter(
                models.Student.name.ilike(query_string),
                course=course
            ).all()
