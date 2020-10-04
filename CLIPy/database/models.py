from datetime import datetime
from enum import Enum

import sqlalchemy as sa
import sqlalchemy.orm as orm
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.ext.declarative import declarative_base

from .types import IntEnum, TupleEnum

Base = declarative_base()


# Static information

class RoomType(Enum):
    #: A room without a specific purpose
    generic = 1
    #: A classroom with chairs tables n' a good ol' blackboard.
    classroom = 2
    #: Some big room which sits a lot of folks.
    auditorium = 3
    #: The rooms in which the practical wombo-mambo happens.
    laboratory = 4
    #: A classroom with computers
    computer = 5
    #: A room meant for meetings ???
    meeting_room = 6
    #: A room reserved for students completing their master's
    masters = 7

    def __str__(self):
        return str(self.name)


class FileType(Enum):
    #: A room without a specific purpose
    image = (1, None)
    #: AKA "acetatos"
    slides = (2, '0ac')
    problems = (3, '1e')
    protocols = (4, '2tr')
    seminar = (5, '3sm')
    exams = (6, 'ex')
    tests = (7, 't')
    support = (8, 'ta')
    others = (9, 'xot')

    def to_url_argument(self):
        return self.value[1]

    @staticmethod
    def from_id(identifier):
        for type in FileType:
            if type.value[0] == identifier:
                return type

    @staticmethod
    def from_url_argument(arg):
        for type in FileType:
            if type.value[1] == arg:
                return type

    def __str__(self):
        return self.name


class EvaluationType(Enum):
    test = 1
    exam = 2
    project = 3


class Degree(Base):
    __tablename__ = 'degrees'
    #: Identifier
    id = sa.Column(sa.Integer, sa.Sequence('degree_id_seq'), primary_key=True)
    #: CLIP representation for this degree
    iid = sa.Column(sa.String(5), nullable=False)
    #: Verbose representation
    name = sa.Column(sa.String, nullable=False)

    # Relations
    courses = orm.relationship("Course", order_by="Course.id", back_populates="degree")

    def __str__(self):
        return self.name


class Period(Base):
    __tablename__ = 'periods'
    #: Identifier
    id = sa.Column(sa.Integer, sa.Sequence('period_id_seq'), primary_key=True)
    #: Part of parts, with the first starting with the academic year (~september)
    part = sa.Column(sa.Integer, nullable=False)
    #: Times this type of period fits in a year (eg: semester = 2, trimester=4)
    parts = sa.Column(sa.Integer, nullable=False)
    #: Letter which describes the type of this period (a - annual, s - semester, t-trimester)
    letter = sa.Column(sa.CHAR, nullable=False)

    # Relation
    class_instances = orm.relationship("ClassInstance", order_by="ClassInstance.year", back_populates="period")

    def __str__(self):
        return "{} out of {}({})".format(self.part, self.parts, self.letter)


class TurnType(Base):
    __tablename__ = 'turn_types'
    #: Identifier
    id = sa.Column(sa.Integer, primary_key=True)
    #: Verbose name
    name = sa.Column(sa.String(30), nullable=False)
    #: Abbreviated name
    abbreviation = sa.Column(sa.String(5), nullable=False)

    # Relation
    # TODO sort by turn number too
    instances = orm.relationship("Turn", order_by="Turn.class_instance_id", back_populates="type")

    def __str__(self):
        return self.name


# Dynamic information

class TemporalEntity:
    first_year = sa.Column(sa.Integer)
    last_year = sa.Column(sa.Integer)

    def has_time_range(self):
        return not (self.first_year is None or self.last_year is None)

    def add_year(self, year):
        if year is None:
            return
        if self.first_year is None:
            self.first_year = year
        if self.last_year is None:
            self.last_year = year

        if self.first_year > year:
            self.first_year = year
        elif self.last_year < year:
            self.last_year = year

    def contains(self, year):
        return self.first_year <= year <= self.last_year

    def __str__(self):
        return ('' if self.first_year is None or self.last_year is None else ' {} - {}'.format(
            self.first_year, self.last_year))


class Building(Base, TemporalEntity):
    __tablename__ = 'buildings'
    #: CLIP generated identifier
    id = sa.Column(sa.Integer, primary_key=True)
    #: CLIP name (usually not the full name)
    name = sa.Column(sa.String(50), nullable=False)

    # Relation
    rooms = orm.relationship("Room", order_by="Room.name", back_populates="building")

    def __str__(self):
        return self.name

    def serialize(self):
        return {
            'id': self.id,
            'name': self.name}


department_teachers = sa.Table(
    'department_teachers', Base.metadata,
    sa.Column('department_id', sa.ForeignKey('departments.id'), primary_key=True),
    sa.Column('teacher_id', sa.ForeignKey('teachers.id'), primary_key=True))


class Department(Base, TemporalEntity):
    __tablename__ = 'departments'
    #: CLIP assigned identifier
    id = sa.Column(sa.Integer, primary_key=True)
    #: Full name
    name = sa.Column(sa.String(50))

    # Relations and constraints
    teachers = orm.relationship("Teacher", secondary=department_teachers, back_populates="departments")

    def __str__(self):
        return "{}({})".format(self.name, self.id) + super().__str__()

    def serialize(self):
        return {
            'id': self.id,
            'name': self.name}

    def serialize_related(self):
        return {
            'id': self.id,
            'name': self.name,
            'classes': [class_.id for class_ in self.classes],
            'teachers': [teacher.id for teacher in self.teachers]}


class Class(Base):
    __tablename__ = 'classes'
    #: CLIP assigned identifier
    id = sa.Column(sa.Integer, primary_key=True)
    #: Full name
    name = sa.Column(sa.String(100))
    #: Acconym-ish name given by someone over the rainbow (probably a nice madam @ divisão académica)
    abbreviation = sa.Column(sa.String(15))
    #: Number of *half* credits (bologna) that this class takes.
    ects = sa.Column(sa.Integer, nullable=True)

    # Relations and constraints
    instances = orm.relationship("ClassInstance", order_by="ClassInstance.year", back_populates="parent")

    def __str__(self):
        return f'{self.name} ({self.id})'

    def serialize(self):
        return {
            'id': self.id,
            'name': self.name,
            'abbr': self.abbreviation,
            'ects': self.ects,
            'instances': [instance.id for instance in self.instances]}


class Room(Base):
    __tablename__ = 'rooms'
    #: CLIP assigned identifier
    id = sa.Column(sa.Integer, primary_key=True)
    #: CLIP name (usually not the full name)
    name = sa.Column(sa.String(70), nullable=False)
    #: The :py:class:`RoomType` which tells the purpose of this room
    room_type = sa.Column(IntEnum(RoomType))
    #: This room's parent building
    building_id = sa.Column(sa.Integer, sa.ForeignKey(Building.id), nullable=False)

    # Relations and constraints
    building = orm.relationship(Building, back_populates="rooms")
    turn_instances = orm.relationship("TurnInstance", order_by="TurnInstance.weekday", back_populates='room')
    __table_args__ = (sa.UniqueConstraint('building_id', 'name', 'room_type', name='un_room'),)

    def __str__(self):
        return "{} - {}".format(self.name, self.building.name)

    def serialize(self):
        return {
            'id': self.id,
            'name': self.name,
            'type': self.room_type.value,
            'building': self.building_id}


class ClassFile(Base):
    __tablename__ = 'class_instance_files'
    class_instance_id = sa.Column(sa.ForeignKey('class_instances.id'), primary_key=True)
    file_id = sa.Column(sa.ForeignKey('files.id'), primary_key=True)
    #: File name (some places don't tell the file name)
    name = sa.Column(sa.String(256), nullable=True)
    #: What this file represents or the category it got dumped into
    file_type = sa.Column(TupleEnum(FileType))
    #: Time at which the file was uploaded
    upload_datetime = sa.Column(sa.DateTime, primary_key=True)
    #: Uploader TODO check if this can be anyone beside teachers and adapt the field
    uploader = sa.Column(sa.String(100))

    # Relations
    class_instance = orm.relationship("ClassInstance", back_populates="file_relations")
    file = orm.relationship("File", back_populates="class_instance_relations")

    def serialize(self):
        return {
            'upload_datetime': self.upload_datetime.isoformat(),
            'uploader': self.uploader,
            'id': self.file_id,
            'name': self.name,
            'type': self.file_type.value[0],
            'hash': self.file.hash,
            'mime': self.file.mime,
            'size': self.file.size}

    def __str__(self):
        return f"{self.name} ({self.class_instance_id}, {self.file_id})"


class File(Base):
    __tablename__ = 'files'
    #: CLIP assigned identifier
    id = sa.Column(sa.Integer, primary_key=True)
    #: Approximate size reported by CLIP (used as a download consistency check)
    size = sa.Column(sa.Integer)
    #: File hash (sha1)
    hash = sa.Column(sa.CHAR(40), nullable=True)
    #: Whether it is locally stored
    downloaded = sa.Column(sa.Boolean, default=False)
    #: Mime type
    mime = sa.Column(sa.String(100), nullable=True)

    # Relations
    class_instance_relations = orm.relationship("ClassFile", back_populates="file")
    class_instances = association_proxy('class_instance_relations', 'class_instance')

    def __str__(self):
        return f"File {self.id} ({self.size / 1024}KB)"

    def serialize(self):
        return {
            'id': self.id,
            'hash': self.hash,
            'mime': self.mime}


class ClassInstance(Base):
    """
    | A ClassInstance is the existence of a :py:class:`Class` with a temporal period associated with it.
    | There's a lot of redundancy between different ClassInstances of the same :py:class:`Class`, but sometimes the
        associated information and related teachers change wildly.
    """
    __tablename__ = 'class_instances'
    #: Crawler generated identifier
    id = sa.Column(sa.Integer, sa.Sequence('class_instance_id_seq'), primary_key=True)
    #: Parent class
    class_id = sa.Column(sa.Integer, sa.ForeignKey(Class.id), nullable=False)
    #: Academic period on which this instance happened
    period_id = sa.Column(sa.Integer, sa.ForeignKey(Period.id), nullable=False)
    #: (Cached) Department where to which this instance belonged
    department_id = sa.Column(sa.Integer, sa.ForeignKey(Department.id), nullable=True)  # TODO nullable=false
    #: Year on which this instance happened
    year = sa.Column(sa.Integer)
    #: JSON encoded representation of the class instance information
    information = sa.Column(sa.Text, nullable=True)

    # Relations and constraints
    department = orm.relationship(Department)
    parent = orm.relationship(Class, back_populates="instances")
    period = orm.relationship(Period, back_populates="class_instances")
    file_relations = orm.relationship(ClassFile, back_populates="class_instance")
    enrollments = orm.relationship("Enrollment", order_by="Enrollment.id", back_populates="class_instance")
    turns = orm.relationship("Turn", order_by="Turn.number", back_populates="class_instance")
    files = association_proxy('file_relations', 'file')
    evaluations = orm.relationship("ClassEvaluations", order_by="ClassEvaluations.datetime",
                                   back_populates="class_instance")
    messages = orm.relationship("ClassMessages", order_by="ClassMessages.datetime", back_populates="class_instance")
    __table_args__ = (
        sa.UniqueConstraint('class_id', 'year', 'period_id', name='un_class_instance'),)

    def __str__(self):
        return "{} on period {} of {}".format(self.parent, self.period, self.year)

    def serialize(self):
        data = {
            'id': self.id,
            'class_id': self.class_id,
            'period': self.period_id,
            'year': self.year,
            'info': self.information,
            'enrollments': [enrollment.id for enrollment in self.enrollments],
            'turns': [turn.id for turn in self.turns],
            'evaluations': [evaluation.id for evaluation in self.evaluations]}
        return data


class ClassEvaluations(Base):
    __tablename__ = 'class_evaluations'
    #: Crawler generated identifier
    id = sa.Column(sa.Integer, sa.Sequence('class_instance_id_seq'), primary_key=True)
    #: Class instance
    class_instance_id = sa.Column(sa.Integer, sa.ForeignKey(ClassInstance.id), nullable=False)
    #: Occasion on which this evaluation will happen/happened
    datetime = sa.Column(sa.DateTime)
    #: Type of evaluation (test, exam, work...)
    evaluation_type = sa.Column(IntEnum(EvaluationType))

    # Relations and constraints
    class_instance = orm.relationship(ClassInstance, back_populates="evaluations")
    __table_args__ = (sa.UniqueConstraint(
        'class_instance_id', 'datetime', 'evaluation_type', name='un_class_evaluation'),)


class StudentCourse(Base, TemporalEntity):
    __tablename__ = 'student_courses'
    id = sa.Column(sa.Integer, sa.Sequence('student_course_id_seq'), primary_key=True)
    student_id = sa.Column(sa.ForeignKey('students.id'))
    course_id = sa.Column(sa.ForeignKey('courses.id'))
    # Relations
    student = orm.relationship("Student", back_populates="course_relations")
    course = orm.relationship("Course", back_populates="student_relations")
    __table_args__ = (sa.UniqueConstraint('student_id', 'course_id', name='un_student_course'),)


class Course(Base, TemporalEntity):
    __tablename__ = 'courses'
    #: CLIP internal identifier
    id = sa.Column(sa.Integer, primary_key=True)
    #: Full name
    name = sa.Column(sa.String(80))
    #: Course acronym
    abbreviation = sa.Column(sa.String(15))
    #: Degree conferred by this course
    degree_id = sa.Column(sa.Integer, sa.ForeignKey(Degree.id))

    # Relations and constraints
    degree = orm.relationship(Degree, back_populates="courses")
    student_relations = orm.relationship(StudentCourse, back_populates="course")
    admissions = orm.relationship("Admission", order_by="Admission.check_date", back_populates="course")
    students = orm.relationship("Student", back_populates="course")
    # students = association_proxy('student_relations', 'student')
    __table_args__ = (sa.UniqueConstraint('id', name='un_course_id'),)

    def __str__(self):
        return ("{}(ID:{} Abbreviation:{}, Degree:{})".format(self.name, self.id, self.abbreviation, self.degree)
                + super().__str__())

    def serialize(self):
        return {
            'id': self.id,
            'name': self.name,
            'abbr': self.abbreviation,
            'deg': self.degree_id,
        }


turn_students = sa.Table(
    'turn_students', Base.metadata,
    sa.Column('turn_id', sa.ForeignKey('turns.id'), primary_key=True),
    sa.Column('student_id', sa.ForeignKey('students.id'), primary_key=True))

turn_teachers = sa.Table(
    'turn_teachers', Base.metadata,
    sa.Column('turn_id', sa.ForeignKey('turns.id'), primary_key=True),
    sa.Column('teacher_id', sa.ForeignKey('teachers.id'), primary_key=True))


class Teacher(Base, TemporalEntity):
    """
    | Represents a teacher (or part of one...)
    | This model is NOT normalized to attempt to solve the issue pointed by
        :py:const:`CLIPy.database.Controller.get_teacher`.
        That's the reason for information redundancy instead of an M2M relationship.
        In theory the same could be done with an M2M, but it would become noticeably worse on performance, and since
        this isn't a huge table some redundancy can be tolerated.
    | TODO In case there's a day I'm feeling specially worthless, benchmark this as a M2M and port if it isn't that bad
    """
    __tablename__ = 'teachers'
    #: CLIP assigned identifier
    id = sa.Column(sa.Integer, primary_key=True)
    #: Full name
    name = sa.Column(sa.String)
    # Relations and constraints
    departments = orm.relationship(Department, secondary=department_teachers, back_populates="teachers")
    turns = orm.relationship('Turn', secondary=turn_teachers, back_populates='teachers')
    class_messages = orm.relationship('ClassMessages')

    def __str__(self):
        return f'{self.name} ({self.id}, {list(self.departments)})'

    def serialize(self):
        return {
            'id': self.id,
            'name': self.name,
            'first_year': self.first_year,
            'last_year': self.last_year,
            'depts': [department.id for department in self.departments]
        }


class Student(Base, TemporalEntity):
    """
    | A CLIP user which is/was doing a course.
    | When a student transfers to another course a new ``iid`` is assigned, so some persons have multiple
        student entries.
    """
    __tablename__ = 'students'
    # #: Crawler assigned ID
    # id = sa.Column(sa.Integer, sa.Sequence( 'student_id_seq'), primary_key=True)
    #: CLIP assigned ID
    id = sa.Column(sa.Integer, primary_key=True)
    #: Student full name
    name = sa.Column(sa.String(100))
    #: CLIP assigned auth abbreviation (eg: john.f)
    abbreviation = sa.Column(sa.String(100), nullable=True)
    #: Student course
    course_id = sa.Column(sa.Integer, sa.ForeignKey(Course.id))
    #: Student sexual gender (0 - grill, 1 - boy)
    gender = sa.Column(sa.Boolean, nullable=True, default=None)
    #: The grade the student obtained at his/her graduation (0-200)
    graduation_grade = sa.Column(sa.Integer, nullable=True, default=None)

    # Relations and constraints
    course = orm.relationship(Course, back_populates="students")  # TODO remove
    enrollments = orm.relationship("Enrollment", order_by="Enrollment.student_year", back_populates="student")
    turns = orm.relationship('Turn', secondary=turn_students, back_populates='students')
    course_relations = orm.relationship(StudentCourse, back_populates="student")
    admission_records = orm.relationship("Admission", order_by="Admission.check_date", back_populates="student")
    courses = association_proxy('course_relations', 'course')
    __table_args__ = (sa.UniqueConstraint('abbreviation', name='un_student_id_abbr'),)

    def __str__(self):
        return "{} ({}, {})".format(self.name, self.id, self.abbreviation)

    def serialize(self):
        return {
            'id': self.id,
            'name': self.name,
            'abbr': self.abbreviation,
            'course': self.course_id,
            'first_year': self.first_year,
            'last_year': self.last_year}


class ClassMessages(Base):
    __tablename__ = 'class_instance_messages'
    #: Generated identifier
    id = sa.Column(sa.Integer, sa.Sequence('class_instance_message_id_seq'), primary_key=True)
    #: Class intance for which the message was broadcasted
    class_instance_id = sa.Column(sa.Integer, sa.ForeignKey(ClassInstance.id))
    #: Teacher who sent the message
    teacher_id = sa.Column(sa.Integer, sa.ForeignKey(Teacher.id))
    #: Message title
    title = sa.Column(sa.String(200), nullable=False)
    #: Message content
    message = sa.Column(sa.Text, nullable=False)
    #: Timestamp of the message broadcast
    datetime = sa.Column(sa.DateTime, nullable=False)

    # Relations and constraints
    teacher = orm.relationship(Teacher, back_populates="class_messages")
    class_instance = orm.relationship(ClassInstance, back_populates="messages")
    __table_args__ = (sa.UniqueConstraint('class_instance_id', 'datetime', name='un_message'),)


class Admission(Base):
    """
    An admission represents a national access contest entry which was successfully accepted.
    Sometimes students reject admissions and they never become "real" CLIP students.
    """
    __tablename__ = 'admissions'
    #: Crawler assigned identifier
    id = sa.Column(sa.Integer, sa.Sequence('admission_id_seq'), primary_key=True)
    #: CLIP student reference (if the student is present)
    student_id = sa.Column(sa.Integer, sa.ForeignKey(Student.id), nullable=True)
    #: Student full name
    name = sa.Column(sa.String(100))
    #: Admission course
    course_id = sa.Column(sa.Integer, sa.ForeignKey(Course.id))
    #: Contest phase
    phase = sa.Column(sa.Integer)
    #: Contest year
    year = sa.Column(sa.Integer)
    #: Admission as the student's n-th option
    option = sa.Column(sa.Integer)
    #: Student current state (as of check_date)
    state = sa.Column(sa.String(50))
    #: Date on which this record was crawled
    check_date = sa.Column(sa.DateTime, default=datetime.now())

    # Relations and constraints
    student = orm.relationship("Student", back_populates="admission_records")
    course = orm.relationship("Course", back_populates="admissions")
    __table_args__ = (
        sa.UniqueConstraint('student_id', 'name', 'year', 'phase', name='un_admission'),)

    def __str__(self):
        return ("{}, admitted to {}({}) (option {}) at the phase {} of the {} contest. {} as of {}".format(
            (self.student.name if self.student_id is not None else self.name),
            self.course.abbreviation, self.course_id, self.option, self.phase, self.year, self.state,
            self.check_date))

    def serialize(self):
        return {
            'id': self.id,
            'student': self.student_id,
            'name': self.name,
            'course': self.course,
            'phase': self.phase,
            'year': self.year,
            'option': self.option,
            'state': self.state,
            'check_date': self.check_date.isoformat()}


class Enrollment(Base):
    """
    An enrollment is a :py:class:`Student` to :py:class:`ClassInstance` relationship
    """
    __tablename__ = 'enrollments'
    #: Generated identifier
    id = sa.Column(sa.Integer, sa.Sequence('enrollement_id_seq'), primary_key=True)
    #: :py:class:`Student` reference
    student_id = sa.Column(sa.Integer, sa.ForeignKey(Student.id))
    #: :py:class:`ClassInstance` reference
    class_instance_id = sa.Column(sa.Integer, sa.ForeignKey(ClassInstance.id))
    #: n-th :py:class:`Student` attempt to do this :py:class:`ClassInstance`
    attempt = sa.Column(sa.SMALLINT)
    #: Student official academic year as of this enrollment
    student_year = sa.Column(sa.Integer)
    #: Special statutes that were applied to this enrollment
    statutes = sa.Column(sa.String(20))
    #: Additional information such as course specialization TODO remove
    observation = sa.Column(sa.String(30))
    #: Whether the enrolled student obtained frequency to this class
    attendance = sa.Column(sa.Boolean, nullable=True, default=None)
    #: Date on which the frequency was published
    attendance_date = sa.Column(sa.Date, nullable=True, default=None)
    #: Whether the student managed to improve his grade. Null if there wasn't an attempt.
    improved = sa.Column(sa.Boolean, nullable=True, default=None)
    #: Grade the student obtained
    improvement_grade = sa.Column(sa.SmallInteger, default=0)
    #: Date on which the improvement was published
    improvement_grade_date = sa.Column(sa.Date, nullable=True, default=None)
    #: Continuous grade that the student obtained
    continuous_grade = sa.Column(sa.SmallInteger, default=0)
    #: Date on which the continuous grade was published
    continuous_grade_date = sa.Column(sa.Date, nullable=True, default=None)
    #: Continuous grade that the student obtained
    exam_grade = sa.Column(sa.SmallInteger, default=0)
    #: Date on which the continuous grade was published
    exam_grade_date = sa.Column(sa.Date, nullable=True, default=None)
    #: Special period grade that the student obtained
    special_grade = sa.Column(sa.SmallInteger, default=0)
    #: Date on which the special period grade was published
    special_grade_date = sa.Column(sa.Date, nullable=True, default=None)
    #: Whether the final result was an approval
    approved = sa.Column(sa.Boolean, nullable=True, default=None)

    # Relations and constraints
    student = orm.relationship("Student", back_populates="enrollments")
    class_instance = orm.relationship("ClassInstance", back_populates="enrollments")
    __table_args__ = (sa.UniqueConstraint('student_id', 'class_instance_id', name='un_enrollment'),)

    def __str__(self):
        return "{} enrolled to {}, attempt:{}, student year:{}, statutes:{}, obs:{}".format(
            self.student, self.class_instance, self.attempt, self.student_year, self.statutes, self.observation)

    def serialize(self):
        return {
            'id': self.id,
            'student': self.student_id,
            'class_instance': self.class_instance_id,
            'attempt': self.attempt,
            'student_year': self.student_year,
            'statutes': self.statutes,
            'attendance': self.attendance,
            'attendance_date': None if self.attendance_date is None else self.attendance_date.isoformat(),
            'improved': self.improved,
            'improvement_grade': self.improvement_grade,
            'improvement_grade_date':
                None if self.improvement_grade_date is None else self.improvement_grade_date.isoformat(),
            'continuous_grade': self.continuous_grade,
            'continuous_grade_date':
                None if self.continuous_grade_date is None else self.continuous_grade_date.isoformat(),
            'exam_grade': self.exam_grade,
            'exam_grade_date': self.exam_grade_date,
            'special_grade': self.special_grade,
            'special_grade_date': None if self.special_grade_date is None else self.special_grade_date.isoformat(),
            'approved': self.approved}


class Turn(Base):
    """
    | The generic concept of a :py:class:`Class` turn, which students enroll to.
    | It has corresponding :py:class:`TurnInstance` entities to represent the physical/temporal existence of this turn.
    """
    __tablename__ = 'turns'
    #: Identifier
    id = sa.Column(sa.Integer, sa.Sequence('turn_id_seq'), primary_key=True)
    #: Parent :py:class:`ClassInstance` for this turn
    class_instance_id = sa.Column(sa.Integer, sa.ForeignKey(ClassInstance.id))
    #: number out of n turns that the parent :py:class:`ClassInstance` has
    number = sa.Column(sa.Integer)
    #: The type of this turn (theoretical, practical, ...)
    type_id = sa.Column(sa.Integer, sa.ForeignKey(TurnType.id))
    #: Number of students enrolled to this turn TODO remove, is redundant
    enrolled = sa.Column(sa.Integer)
    #: Turn capacity TODO remove, is redundant
    capacity = sa.Column(sa.Integer)
    #: Turn duration TODO remove, is redundant
    minutes = sa.Column(sa.Integer)
    #: sa.String representation of the routes
    routes = sa.Column(sa.String(5000))  # TODO do this properly with relationships
    #: Restrictions to this turn's admission
    restrictions = sa.Column(sa.String(200))  # FIXME enum?
    #: Turn current state (opened, closed, these are left unchanged once the class ends)
    state = sa.Column(sa.String(200))  # FIXME enum?

    # Relations and constraints
    teachers = orm.relationship(Teacher, secondary=turn_teachers, back_populates='turns')
    students = orm.relationship(Student, secondary=turn_students, back_populates='turns')
    class_instance = orm.relationship("ClassInstance", back_populates="turns")
    instances = orm.relationship(
        "TurnInstance",
        order_by="TurnInstance.weekday",
        back_populates='turn',
        cascade="save-update, merge, delete")
    type = orm.relationship("TurnType", back_populates="instances")
    __table_args__ = (
        sa.UniqueConstraint('class_instance_id', 'number', 'type_id', name='un_turn'),)

    def __str__(self):
        return "{} {}.{}".format(self.class_instance, self.type, self.number)

    def serialize(self):
        return {
            'id': self.id,
            'class_instance_id': self.class_instance_id,
            'number': self.number,
            'type': self.type.abbreviation,
            'minutes': self.minutes,
            'restrictions': self.restrictions,
            'state': self.state,
            'teachers': [teacher.id for teacher in self.teachers],
            'students': [student.id for student in self.students],
            'instances': [instance.id for instance in self.instances]
        }


class TurnInstance(Base):
    """
    | An instance of a :py:class:`Turn`.
    | This represents the physical and temporal presences a turn.
    """
    __tablename__ = 'turn_instances'
    #: Identifier
    id = sa.Column(sa.Integer, sa.Sequence('turn_instance_id_seq'), primary_key=True)
    #: Parent :py:class:`Turn`
    turn_id = sa.Column(sa.Integer, sa.ForeignKey(Turn.id))
    #: Starting time (in minutes counting from the midnight)
    start = sa.Column(sa.Integer)
    #: Ending time (in minutes, counting from the midnight)
    end = sa.Column(sa.Integer)
    #: :py:class:`Room` in which it happens
    room_id = sa.Column(sa.Integer, sa.ForeignKey(Room.id))
    #: Weekday in which it happens
    weekday = sa.Column(sa.SMALLINT)

    # Relations and constraints
    turn = orm.relationship(Turn, back_populates='instances')
    room = orm.relationship(Room, back_populates="turn_instances")
    __table_args__ = (sa.UniqueConstraint('turn_id', 'start', 'weekday', name='un_turn_instance'),)

    @staticmethod
    def minutes_to_str(minutes: int):
        return "{}:{}".format(minutes / 60, minutes % 60)

    def serialize(self):
        return {
            'id': self.id,
            'turn': self.turn_id,
            'start': self.start,
            'end': self.end,
            'room': self.room_id,
            'weekday': self.weekday}

    def __str__(self):
        return "{}, weekday {}, hour {}".format(self.turn, self.weekday, self.minutes_to_str(self.start))
