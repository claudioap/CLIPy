from datetime import datetime

from . import models


class TemporalEntity:
    def __init__(self, identifier, first_year, last_year):
        self.id = identifier
        self.first_year = first_year
        self.last_year = last_year

    def has_time_range(self):
        return not (self.first_year is None or self.last_year is None)

    def add_year(self, year):
        if self.first_year is None:
            self.first_year = year
        if self.last_year is None:
            self.last_year = year

        if self.first_year > year:
            self.first_year = year
        elif self.last_year < year:
            self.last_year = year

    def __str__(self):
        return ('' if self.first_year is None or self.last_year is None else ' {} - {}'.format(
            self.first_year, self.last_year))


class Department(TemporalEntity):
    def __init__(self, identifier: int, name: str, first_year=None, last_year=None):
        super().__init__(identifier, first_year=first_year, last_year=last_year)
        self.name = name

    def __str__(self):
        return self.name


class Degree:
    def __init__(self, identifier, name):
        self.id = identifier
        self.name = name

    def __str__(self):
        return self.name


class Class:
    def __init__(self, identifier: int, name: str, department: models.Department, abbreviation, ects):
        self.id = identifier
        self.name = name
        self.department = department
        self.abbreviation = abbreviation
        self.ects = ects

    def __str__(self):
        return f'{self.name} ({self.id}, {self.department})'


class ClassInstance:
    def __init__(self, parent: Class, period: int, year: int, department=None):
        self.parent = parent
        self.period = period
        self.year = year
        self.department = department

    def __str__(self):
        return "{} on period {} of {}".format(self.parent, self.period, self.year)


class Course(TemporalEntity):
    def __init__(self, identifier: int, name: str, degree=None, abbreviation=None, first_year=None, last_year=None):
        super().__init__(identifier, first_year, last_year)
        self.name = name
        self.abbreviation = abbreviation
        self.degree = degree

    def __str__(self):
        return "{} ({})".format(self.name, self.degree.name)


class Student(TemporalEntity):
    def __init__(self, identifier, name: str, course: models.Course,
                 abbreviation=None, first_year: int = None, last_year: int = None):
        super().__init__(identifier, first_year, last_year)
        self.name = ' '.join(name.split())
        self.course = course
        self.abbreviation = abbreviation

    def __str__(self):
        return "{} ({}, {})".format(self.name, self.id, self.abbreviation)


class Teacher(TemporalEntity):
    def __init__(self, identifier: int, name: str, department: Department,
                 first_year: int = None, last_year: int = None):
        super().__init__(identifier, first_year, last_year)
        self.name = name
        self.department = department
        self.schedule_entries = dict()

    def __str__(self):
        return f'{self.name} ({self.id}, {self.department.name})'

    def add_shift(self, shift: models.Shift):
        key = (shift.class_instance.year, shift.class_instance.period)
        if key in self.schedule_entries:
            self.schedule_entries[key].add(shift)
        else:
            self.schedule_entries[key] = {shift, }


class Admission:
    def __init__(self, student, name: str, course: models.Course, phase: int, year: int, option: int, state,
                 check_date=None):
        self.student = student
        self.name = name
        self.course = course
        self.phase = phase
        self.year = year
        self.option = option
        self.state = state
        self.check_date = check_date if check_date is not None else datetime.now()

    def __str__(self):
        return "{}, admitted to {} (opt: {}, phase: {}) {} contest. {} as of {}".format(
            (self.student.name if self.student is not None else self.name),
            self.course.name, self.option, self.phase, self.year, self.state, self.check_date)


class Enrollment:
    def __init__(self, student: models.Student, class_instance: models.ClassInstance, attempt: int, student_year: int,
                 statutes, observation):
        self.student = student
        self.class_instance = class_instance
        self.attempt = attempt
        self.student_year = student_year
        self.statutes = statutes
        self.observation = observation

    def __str__(self):
        return "{} enrolled to {}, attempt:{}, student year:{}, statutes:{}, obs:{}".format(
            self.student, self.class_instance, self.attempt, self.student_year, self.statutes, self.observation)


class Building(TemporalEntity):
    def __init__(self, identifier: int, name: str,
                 first_year: int = None, last_year: int = None):
        super().__init__(identifier, first_year, last_year)
        if name is None:
            raise ValueError("A building must have a name")
        self.id = identifier
        self.name = name

    def __str__(self):
        return self.name

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        if isinstance(self, other.__class__):
            return self.id == other.id and self.name == other.name


class Room:
    def __init__(self, identifier: int, name, room_type: models.RoomType, building: models.Building):
        if name is None:
            raise ValueError("A room must have a name")
        if building is None:
            raise ValueError("A room must belong to a building")
        self.id = identifier
        self.name = name
        self.type = room_type
        self.building = building

    def __str__(self):
        return "{} {}, {}".format(self.type, self.name, self.building.name)

    def __eq__(self, other):
        if isinstance(self, other.__class__):
            return self.id == other.id and self.name == other.name and self.type == other.type


class Shift:
    def __init__(self, class_instance: models.ClassInstance, number: int, shift_type: models.ShiftType, enrolled: int,
                 capacity: int, minutes=None, routes=None, restrictions=None, state=None):
        self.class_instance = class_instance
        self.number = number
        self.type = shift_type
        self.enrolled = enrolled
        self.capacity = capacity
        self.minutes = minutes
        self.routes = routes
        self.restrictions = restrictions
        self.state = state

    def __str__(self):
        return "shift {}.{} of {} {}/{} students, {} hours, {} routes, state: {}".format(
            self.type, self.number, self.class_instance, self.enrolled, self.capacity,
            self.minutes / 60, self.routes, self.state)

    def __hash__(self):
        return self.class_instance.id.__hash__() + self.type.id.__hash__() + (self.number + 100).__hash__()


class ShiftInstance:
    def __init__(self, shift: models.Shift, start: int, end: int, weekday: int, room=None):
        self.shift = shift
        self.start = start
        self.end = end
        self.weekday = weekday
        self.room = room

    @staticmethod
    def time_str(time):
        return "{}:{}".format(time / 60, time % 60)

    def __str__(self):
        return "{} to {}, day:{}, shift{}".format(
            self.time_str(self.start), self.time_str(self.end), self.weekday, self.shift)


class File:
    def __init__(self, identifier: int, name: str, upload_datetime: datetime, uploader: str, file_type: models.FileType,
                 size: int, file_hash: str = None, location: str = None):
        self.id = identifier
        self.name = name
        self.upload_datetime = upload_datetime
        self.uploader = uploader
        self.file_type = file_type
        self.size = size
        self.hash = file_hash
        self.location = location
