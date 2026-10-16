"""Adaptadores: os serviços do núcleo (agenda, estoque, relatórios, assistente)
rodam no servidor sobre o PostgreSQL/SQLite do backend.

Os serviços de ``medremind.core`` dependem só da *interface* dos repositórios
(list/get/add/update/...). Aqui implementamos essa interface com SQLAlchemy,
restrita a um paciente. Assim a regra de negócio é a mesma no app e no servidor.
"""
from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from medremind.core import models as dm
from medremind.core.repositories import utcnow_iso
from medremind.core.services.assistant import Assistant, AssistantTools
from medremind.core.services.audit import AuditService
from medremind.core.services.hydration import HydrationService
from medremind.core.services.medications import MedicationService
from medremind.core.services.reports import ReportService
from medremind.core.services.schedule import ScheduleService

from . import orm


def bump(db: Session, patient: orm.Patient) -> int:
    """Próximo número de sequência de alteração do paciente (cursor da sincronização).

    O incremento é atômico no banco (UPDATE ... RETURNING): a linha do paciente fica
    travada até o commit, então duas requisições simultâneas nunca recebem o mesmo seq.
    """
    with db.no_autoflush:
        seq = db.execute(update(orm.Patient).where(orm.Patient.id == patient.id)
                         .values(sync_seq=orm.Patient.sync_seq + 1).returning(orm.Patient.sync_seq)).scalar_one()
    set_committed_value(patient, "sync_seq", seq)
    return seq


def patient_clock(patient: orm.Patient):
    tz = ZoneInfo(patient.timezone or "America/Sao_Paulo")
    return lambda: datetime.now(tz).replace(tzinfo=None, microsecond=0)


# ------------------------------------------------------------------- conversões
def med_to_domain(r: orm.Medication) -> dm.Medication:
    return dm.Medication(
        id=r.id, name=r.name, strength=r.strength, form=dm.MedForm(r.form), dose_units=r.dose_units,
        frequency=dm.Frequency(r.frequency), times=[time.fromisoformat(t) for t in r.times.split(",") if t],
        weekdays=[int(x) for x in r.weekdays.split(",") if x != ""], instructions=r.instructions,
        start_date=r.start_date, end_date=r.end_date, track_stock=r.track_stock, stock_units=r.stock_units,
        stock_total=r.stock_total, refill_alert_days=r.refill_alert_days, reminders=r.reminders, paused=r.paused,
    )


def apply_med_fields(r: orm.Medication, m: dm.Medication) -> None:
    r.name, r.strength, r.form = m.name.strip(), m.strength.strip(), m.form.value
    r.dose_units, r.frequency = m.dose_units, m.frequency.value
    r.times = ",".join(sorted(t.strftime("%H:%M") for t in m.times))
    r.weekdays = ",".join(str(w) for w in sorted(set(m.weekdays)))
    r.instructions, r.start_date, r.end_date = m.instructions.strip(), m.start_date, m.end_date
    r.track_stock, r.stock_units, r.stock_total = m.track_stock, m.stock_units, m.stock_total
    r.refill_alert_days, r.reminders, r.paused = m.refill_alert_days, m.reminders, m.paused


# ------------------------------------------------------------------ repositórios
class _Base:
    def __init__(self, db: Session, patient: orm.Patient) -> None:
        self.db = db
        self.patient = patient

    def _touch(self, row) -> None:
        row.updated_at = utcnow_iso()
        row.seq = bump(self.db, self.patient)


class SqlMedicationRepo(_Base):
    def _q(self):
        return select(orm.Medication).where(orm.Medication.patient_id == self.patient.id,
                                            orm.Medication.deleted.is_(False))

    def list(self, include_paused: bool = True) -> list[dm.Medication]:
        q = self._q()
        if not include_paused:
            q = q.where(orm.Medication.paused.is_(False))
        rows = self.db.scalars(q.order_by(orm.Medication.paused, orm.Medication.name)).all()
        return [med_to_domain(r) for r in rows]

    def row(self, med_id: int) -> orm.Medication | None:
        return self.db.scalar(self._q().where(orm.Medication.id == med_id))

    def get(self, med_id: int) -> dm.Medication | None:
        r = self.row(med_id)
        return med_to_domain(r) if r else None

    def add(self, m: dm.Medication) -> dm.Medication:
        r = orm.Medication(patient_id=self.patient.id)
        apply_med_fields(r, m)
        self._touch(r)
        self.db.add(r)
        self.db.flush()
        m.id = r.id
        return m

    def update(self, m: dm.Medication) -> dm.Medication:
        r = self.row(m.id)
        if r is None:
            raise ValueError("Medicação não encontrada")
        apply_med_fields(r, m)
        self._touch(r)
        return m

    def adjust_stock(self, med_id: int, delta: float) -> None:
        r = self.row(med_id)
        if r and r.track_stock:
            r.stock_units = max(0.0, r.stock_units + delta)
            self._touch(r)

    def delete(self, med_id: int) -> None:
        r = self.row(med_id)
        if r:
            r.deleted = True
            self._touch(r)
            for log in self.db.scalars(select(orm.DoseLog).where(orm.DoseLog.medication_id == med_id)):
                log.deleted = True
                self._touch(log)


class SqlDoseLogRepo(_Base):
    @staticmethod
    def _to(r: orm.DoseLog) -> dm.DoseLog:
        return dm.DoseLog(id=r.id, medication_id=r.medication_id, scheduled_at=r.scheduled_at,
                          status=dm.DoseStatus(r.status), acted_at=r.acted_at, snoozed_until=r.snoozed_until,
                          note=r.note)

    def _q(self):
        return select(orm.DoseLog).where(orm.DoseLog.patient_id == self.patient.id, orm.DoseLog.deleted.is_(False))

    def between(self, start: datetime, end: datetime) -> list[dm.DoseLog]:
        rows = self.db.scalars(self._q().where(orm.DoseLog.scheduled_at >= start, orm.DoseLog.scheduled_at < end)
                               .order_by(orm.DoseLog.scheduled_at)).all()
        return [self._to(r) for r in rows]

    def _row(self, med_id: int, at: datetime, include_deleted: bool = False):
        q = select(orm.DoseLog).where(orm.DoseLog.medication_id == med_id, orm.DoseLog.scheduled_at == at,
                                      orm.DoseLog.patient_id == self.patient.id)
        if not include_deleted:
            q = q.where(orm.DoseLog.deleted.is_(False))
        return self.db.scalar(q)

    def get(self, med_id: int, scheduled_at: datetime) -> dm.DoseLog | None:
        r = self._row(med_id, scheduled_at)
        return self._to(r) if r else None

    def upsert(self, log: dm.DoseLog) -> None:
        r = self._row(log.medication_id, log.scheduled_at, include_deleted=True)
        if r is None:
            r = orm.DoseLog(patient_id=self.patient.id, medication_id=log.medication_id,
                            scheduled_at=log.scheduled_at)
            self.db.add(r)
        r.status, r.acted_at, r.snoozed_until, r.note = log.status.value, log.acted_at, log.snoozed_until, log.note
        r.deleted = False
        self._touch(r)
        self.db.flush()

    def delete(self, med_id: int, scheduled_at: datetime) -> None:
        r = self._row(med_id, scheduled_at)
        if r:
            r.deleted = True
            self._touch(r)

    def all(self) -> list[dm.DoseLog]:
        return [self._to(r) for r in self.db.scalars(self._q().order_by(orm.DoseLog.scheduled_at)).all()]


class SqlWaterRepo(_Base):
    def add(self, log: dm.WaterLog) -> dm.WaterLog:
        r = orm.WaterLog(patient_id=self.patient.id, amount_ml=log.amount_ml, kind=log.kind, logged_at=log.logged_at)
        self._touch(r)
        self.db.add(r)
        self.db.flush()
        log.id = r.id
        return log

    def between(self, start: datetime, end: datetime) -> list[dm.WaterLog]:
        rows = self.db.scalars(select(orm.WaterLog).where(
            orm.WaterLog.patient_id == self.patient.id, orm.WaterLog.deleted.is_(False),
            orm.WaterLog.logged_at >= start, orm.WaterLog.logged_at < end).order_by(orm.WaterLog.logged_at.desc())).all()
        return [dm.WaterLog(id=r.id, amount_ml=r.amount_ml, kind=r.kind, logged_at=r.logged_at) for r in rows]

    def delete(self, log_id: int) -> None:
        r = self.db.get(orm.WaterLog, log_id)
        if r and r.patient_id == self.patient.id:
            r.deleted = True
            self._touch(r)


class SqlContactRepo(_Base):
    def list(self) -> list[dm.Contact]:
        rows = self.db.scalars(select(orm.Contact).where(orm.Contact.patient_id == self.patient.id,
                                                         orm.Contact.deleted.is_(False))
                               .order_by(orm.Contact.is_doctor, orm.Contact.name)).all()
        return [dm.Contact(id=r.id, name=r.name, relation=r.relation, phone=r.phone, is_doctor=r.is_doctor)
                for r in rows]

    def add(self, c: dm.Contact) -> dm.Contact:
        r = orm.Contact(patient_id=self.patient.id, name=c.name.strip(), relation=c.relation.strip(),
                        phone=c.phone.strip(), is_doctor=c.is_doctor)
        self._touch(r)
        self.db.add(r)
        self.db.flush()
        c.id = r.id
        return c

    def delete(self, contact_id: int) -> None:
        r = self.db.get(orm.Contact, contact_id)
        if r and r.patient_id == self.patient.id:
            r.deleted = True
            self._touch(r)


class SqlSettingsRepo(_Base):
    """Só o que os serviços usam: o perfil do paciente."""

    def profile(self) -> dm.Profile:
        data = dict(self.patient.profile or {})
        if data.get("birth_date"):
            data["birth_date"] = date.fromisoformat(data["birth_date"])
        return dm.Profile(**{k: v for k, v in data.items() if k in dm.Profile.__dataclass_fields__})

    def save_profile(self, p: dm.Profile) -> None:
        data = dict(p.__dict__)
        data["birth_date"] = p.birth_date.isoformat() if p.birth_date else None
        self.patient.profile = data
        self.patient.profile_updated_at = utcnow_iso()
        bump(self.db, self.patient)

    def get(self, key, default=None):  # usado por ReminderEngine/Hydration em alguns caminhos
        return default


class SqlAuditRepo:
    def __init__(self, db: Session, patient: orm.Patient, user_id: int | None, ip: str = "") -> None:
        self.db, self.patient, self.user_id, self.ip = db, patient, user_id, ip

    def add(self, event: str, detail: str, at: datetime) -> None:
        self.db.add(orm.AuditEvent(patient_id=self.patient.id, user_id=self.user_id, event=event,
                                   detail=detail[:500], ip=self.ip))

    def recent(self, limit: int = 50) -> list[dm.AuditEntry]:
        rows = self.db.scalars(select(orm.AuditEvent).where(orm.AuditEvent.patient_id == self.patient.id)
                               .order_by(orm.AuditEvent.id.desc()).limit(limit)).all()
        return [dm.AuditEntry(id=r.id, event=r.event, detail=r.detail, created_at=r.created_at) for r in rows]


class PatientCore:
    """Os mesmos serviços do app, ligados ao banco do servidor para um paciente."""

    def __init__(self, db: Session, patient: orm.Patient, user_id: int | None = None, ip: str = "",
                 clock=None, api_key: str = "", read_only: bool = False) -> None:
        self.db = db
        self.patient = patient
        self.clock = clock or patient_clock(patient)
        self.audit = AuditService(SqlAuditRepo(db, patient, user_id, ip), self.clock)
        self.med_repo = SqlMedicationRepo(db, patient)
        self.meds = MedicationService(self.med_repo, self.audit, self.clock)
        self.schedule = ScheduleService(self.med_repo, SqlDoseLogRepo(db, patient), self.audit, self.clock)
        self.settings = SqlSettingsRepo(db, patient)
        self.contacts = SqlContactRepo(db, patient)
        self.hydration = HydrationService(SqlWaterRepo(db, patient), self.settings, self.clock)
        self.reports = ReportService(self.schedule, self.meds, self.settings, self.audit, self.clock)
        tools = AssistantTools(self.schedule, self.meds, self.hydration, self.contacts)
        if read_only:
            for name in AssistantTools.MUTATING:
                tools.tools[name].handler = lambda **_: "Acesso somente leitura: não posso registrar nada aqui."
        self.assistant = Assistant(tools, api_key)
