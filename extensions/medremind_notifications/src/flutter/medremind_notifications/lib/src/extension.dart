import 'package:flet/flet.dart';

import 'notifications.dart';

class Extension extends FletExtension {
  @override
  FletService? createService(Control control) {
    switch (control.type) {
      case "MedRemindNotifications":
        return MedRemindNotificationsService(control: control);
      default:
        return null;
    }
  }
}
