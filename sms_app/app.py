import customtkinter as ctk
from sms_app.views.auth import AuthMixin
from sms_app.views.dashboard import DashboardMixin
from sms_app.views.students import StudentsMixin
from sms_app.views.attendance import AttendanceMixin
from sms_app.views.academics import AcademicsMixin
from sms_app.views.admin import AdminMixin
from sms_app.views.student import StudentMixin
from sms_app.views.base import BaseSMS

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

class SMS(AuthMixin, DashboardMixin, StudentsMixin, AttendanceMixin, AcademicsMixin, AdminMixin, StudentMixin, BaseSMS):
    pass
