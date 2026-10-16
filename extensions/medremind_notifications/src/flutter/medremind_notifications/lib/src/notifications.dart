import 'dart:io' show Platform;

import 'package:flet/flet.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:flutter_timezone/flutter_timezone.dart';
import 'package:timezone/data/latest_all.dart' as tzdata;
import 'package:timezone/timezone.dart' as tz;

/// Agenda lembretes no sistema operacional com flutter_local_notifications.
/// Os avisos disparam com o app fechado e sobrevivem a reinícios do aparelho.
class MedRemindNotificationsService extends FletService {
  MedRemindNotificationsService({required super.control});

  final FlutterLocalNotificationsPlugin _plugin = FlutterLocalNotificationsPlugin();
  bool _ready = false;

  @override
  void init() {
    super.init();
    control.addInvokeMethodListener(_invokeMethod);
  }

  Future<void> _ensureReady() async {
    if (_ready) return;
    tzdata.initializeTimeZones();
    try {
      final info = await FlutterTimezone.getLocalTimezone();
      tz.setLocalLocation(tz.getLocation(info.identifier));
    } catch (_) {
      tz.setLocalLocation(tz.getLocation("America/Sao_Paulo"));
    }
    const settings = InitializationSettings(
      android: AndroidInitializationSettings("@mipmap/ic_launcher"),
      iOS: DarwinInitializationSettings(
        requestAlertPermission: false,
        requestBadgePermission: false,
        requestSoundPermission: false,
      ),
      macOS: DarwinInitializationSettings(
        requestAlertPermission: false,
        requestBadgePermission: false,
        requestSoundPermission: false,
      ),
    );
    await _plugin.initialize(settings);
    _ready = true;
  }

  NotificationDetails _details() {
    final channelName = control.getString("channel_name", "Lembretes de remédios")!;
    final channelDescription =
        control.getString("channel_description", "Avisos no horário de cada dose")!;
    return NotificationDetails(
      android: AndroidNotificationDetails(
        "medremind_doses",
        channelName,
        channelDescription: channelDescription,
        importance: Importance.max,
        priority: Priority.high,
        category: AndroidNotificationCategory.reminder,
        visibility: NotificationVisibility.private, // conteúdo oculto na tela bloqueada
      ),
      iOS: const DarwinNotificationDetails(interruptionLevel: InterruptionLevel.timeSensitive),
      macOS: const DarwinNotificationDetails(),
    );
  }

  Future<bool> _requestPermission() async {
    await _ensureReady();
    if (!kIsWeb && Platform.isAndroid) {
      final android = _plugin.resolvePlatformSpecificImplementation<
          AndroidFlutterLocalNotificationsPlugin>();
      final granted = await android?.requestNotificationsPermission() ?? false;
      await android?.requestExactAlarmsPermission();
      return granted;
    }
    if (!kIsWeb && Platform.isIOS) {
      final ios = _plugin.resolvePlatformSpecificImplementation<
          IOSFlutterLocalNotificationsPlugin>();
      return await ios?.requestPermissions(alert: true, badge: true, sound: true) ?? false;
    }
    if (!kIsWeb && Platform.isMacOS) {
      final mac = _plugin.resolvePlatformSpecificImplementation<
          MacOSFlutterLocalNotificationsPlugin>();
      return await mac?.requestPermissions(alert: true, badge: true, sound: true) ?? false;
    }
    return false;
  }

  Future<int> _replaceAll(List<dynamic> items) async {
    await _ensureReady();
    await _plugin.cancelAll();
    final details = _details();
    final now = tz.TZDateTime.now(tz.local);
    var count = 0;
    for (final raw in items) {
      final item = Map<String, dynamic>.from(raw as Map);
      final local = DateTime.parse(item["at"] as String);
      final when = tz.TZDateTime(tz.local, local.year, local.month, local.day, local.hour, local.minute);
      if (!when.isAfter(now)) continue;
      await _plugin.zonedSchedule(
        item["id"] as int,
        item["title"] as String,
        item["body"] as String,
        when,
        details,
        androidScheduleMode: AndroidScheduleMode.exactAllowWhileIdle,
        payload: item["payload"] as String?,
      );
      count++;
    }
    return count;
  }

  Future<dynamic> _invokeMethod(String name, dynamic args) async {
    switch (name) {
      case "request_permission":
        return await _requestPermission();
      case "replace_all":
        return await _replaceAll((args["items"] as List<dynamic>?) ?? const []);
      case "cancel_all":
        await _ensureReady();
        await _plugin.cancelAll();
        return null;
      case "pending_count":
        await _ensureReady();
        return (await _plugin.pendingNotificationRequests()).length;
      default:
        throw Exception("Método desconhecido em MedRemindNotifications: $name");
    }
  }

  @override
  void dispose() {
    control.removeInvokeMethodListener(_invokeMethod);
    super.dispose();
  }
}
