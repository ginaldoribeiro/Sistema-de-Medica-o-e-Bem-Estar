"""Lembretes locais agendados pelo sistema operacional (Android/iOS/macOS).

O app agenda as próximas doses; o aviso aparece no horário mesmo com o app
fechado ou o celular reiniciado. Em plataformas sem a extensão (web, Linux,
desenvolvimento no desktop) o ``ReminderScheduler`` informa indisponível e o
MedRemind usa os lembretes dentro do app.
"""
from medremind_notifications.notifications import MedRemindNotifications, ScheduledReminder

__all__ = ["MedRemindNotifications", "ScheduledReminder"]
