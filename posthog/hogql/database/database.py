import dataclasses
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Optional, TypeAlias, Union, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db.models import Prefetch, Q
from pydantic import BaseModel, ConfigDict

from posthog.exceptions_capture import capture_exception
from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DatabaseField,
    DateDatabaseField,
    DateTimeDatabaseField,
    ExpressionField,
    FieldOrTable,
    FieldTraverser,
    FloatDatabaseField,
    FunctionCallTable,
    IntegerDatabaseField,
    LazyJoin,
    SavedQuery,
    StringArrayDatabaseField,
    StringDatabaseField,
    StringJSONDatabaseField,
    Table,
    VirtualTable,
)
from posthog.hogql.database.schema.app_metrics2 import AppMetrics2Table
from posthog.hogql.database.schema.channel_type import create_initial_channel_type, create_initial_domain_type
from posthog.hogql.database.schema.cohort_people import CohortPeople, RawCohortPeople
from posthog.hogql.database.schema.error_tracking_issue_fingerprint_overrides import (
    ErrorTrackingIssueFingerprintOverridesTable,
    RawErrorTrackingIssueFingerprintOverridesTable,
    join_with_error_tracking_issue_fingerprint_overrides_table,
)
from posthog.hogql.database.schema.events import EventsTable
from posthog.hogql.database.schema.exchange_rate import ExchangeRateTable
from posthog.hogql.database.schema.groups import GroupsTable, RawGroupsTable
from posthog.hogql.database.schema.heatmaps import HeatmapsTable
from posthog.hogql.database.schema.log_entries import (
    BatchExportLogEntriesTable,
    LogEntriesTable,
    ReplayConsoleLogsLogEntriesTable,
)
from posthog.hogql.database.schema.numbers import NumbersTable
from posthog.hogql.database.schema.person_distinct_id_overrides import (
    PersonDistinctIdOverridesTable,
    RawPersonDistinctIdOverridesTable,
    join_with_person_distinct_id_overrides_table,
)
from posthog.hogql.database.schema.person_distinct_ids import (
    PersonDistinctIdsTable,
    RawPersonDistinctIdsTable,
)
from posthog.hogql.database.schema.persons import (
    PersonsTable,
    RawPersonsTable,
    join_with_persons_table,
)
from posthog.hogql.database.schema.pg_embeddings import PgEmbeddingsTable
from posthog.hogql.database.schema.query_log import QueryLogTable, RawQueryLogTable
from posthog.hogql.database.schema.session_replay_events import (
    RawSessionReplayEventsTable,
    SessionReplayEventsTable,
    join_replay_table_to_sessions_table_v2,
)
from posthog.hogql.database.schema.sessions_v1 import RawSessionsTableV1, SessionsTableV1
from posthog.hogql.database.schema.sessions_v2 import (
    RawSessionsTableV2,
    SessionsTableV2,
    join_events_table_to_sessions_table_v2,
)
from posthog.hogql.database.schema.static_cohort_people import StaticCohortPeople
from posthog.hogql.errors import QueryError, ResolutionError
from posthog.hogql.parser import parse_expr
from posthog.hogql.timings import HogQLTimings
from posthog.models.group_type_mapping import GroupTypeMapping
from posthog.models.team.team import WeekStartDay
from posthog.schema import (
    DatabaseSchemaDataWarehouseTable,
    DatabaseSchemaField,
    DatabaseSchemaPostHogTable,
    DatabaseSchemaSchema,
    DatabaseSchemaSource,
    DatabaseSchemaViewTable,
    DatabaseSerializedFieldType,
    HogQLQuery,
    HogQLQueryModifiers,
    PersonsOnEventsMode,
    SessionTableVersion,
)
from posthog.warehouse.models.external_data_job import ExternalDataJob
from posthog.warehouse.models.table import (
    DataWarehouseTable,
    DataWarehouseTableColumns,
)

if TYPE_CHECKING:
    from posthog.models import Team


class Database(BaseModel):
    model_config = ConfigDict(extra="allow")

    # Users can query from the tables below
    events: EventsTable = EventsTable()
    groups: GroupsTable = GroupsTable()
    persons: PersonsTable = PersonsTable()
    person_distinct_ids: PersonDistinctIdsTable = PersonDistinctIdsTable()
    person_distinct_id_overrides: PersonDistinctIdOverridesTable = PersonDistinctIdOverridesTable()
    error_tracking_issue_fingerprint_overrides: ErrorTrackingIssueFingerprintOverridesTable = (
        ErrorTrackingIssueFingerprintOverridesTable()
    )

    session_replay_events: SessionReplayEventsTable = SessionReplayEventsTable()
    cohort_people: CohortPeople = CohortPeople()
    static_cohort_people: StaticCohortPeople = StaticCohortPeople()
    log_entries: LogEntriesTable = LogEntriesTable()
    query_log: QueryLogTable = QueryLogTable()
    app_metrics: AppMetrics2Table = AppMetrics2Table()
    console_logs_log_entries: ReplayConsoleLogsLogEntriesTable = ReplayConsoleLogsLogEntriesTable()
    batch_export_log_entries: BatchExportLogEntriesTable = BatchExportLogEntriesTable()
    sessions: Union[SessionsTableV1, SessionsTableV2] = SessionsTableV1()
    heatmaps: HeatmapsTable = HeatmapsTable()
    exchange_rate: ExchangeRateTable = ExchangeRateTable()

    raw_session_replay_events: RawSessionReplayEventsTable = RawSessionReplayEventsTable()
    raw_person_distinct_ids: RawPersonDistinctIdsTable = RawPersonDistinctIdsTable()
    raw_persons: RawPersonsTable = RawPersonsTable()
    raw_groups: RawGroupsTable = RawGroupsTable()
    raw_cohort_people: RawCohortPeople = RawCohortPeople()
    raw_person_distinct_id_overrides: RawPersonDistinctIdOverridesTable = RawPersonDistinctIdOverridesTable()
    raw_error_tracking_issue_fingerprint_overrides: RawErrorTrackingIssueFingerprintOverridesTable = (
        RawErrorTrackingIssueFingerprintOverridesTable()
    )
    raw_sessions: Union[RawSessionsTableV1, RawSessionsTableV2] = RawSessionsTableV1()
    raw_query_log: RawQueryLogTable = RawQueryLogTable()
    pg_embeddings: PgEmbeddingsTable = PgEmbeddingsTable()

    # system tables
    numbers: NumbersTable = NumbersTable()

    # These are the tables exposed via SQL editor autocomplete and data management
    _table_names: ClassVar[list[str]] = [
        "events",
        "groups",
        "persons",
        "sessions",
        "query_log",
    ]

    _warehouse_table_names: list[str] = []
    _view_table_names: list[str] = []

    _timezone: Optional[str]
    _week_start_day: Optional[WeekStartDay]

    def __init__(self, timezone: Optional[str] = None, week_start_day: Optional[WeekStartDay] = None):
        super().__init__()
        try:
            self._timezone = str(ZoneInfo(timezone)) if timezone else None
        except ZoneInfoNotFoundError:
            raise ValueError(f"Unknown timezone: '{str(timezone)}'")
        self._week_start_day = week_start_day

    def get_timezone(self) -> str:
        return self._timezone or "UTC"

    def get_week_start_day(self) -> WeekStartDay:
        return self._week_start_day or WeekStartDay.SUNDAY

    def has_table(self, table_name: str) -> bool:
        return hasattr(self, table_name)

    def get_table(self, table_name: str) -> Table:
        if self.has_table(table_name):
            return getattr(self, table_name)
        raise QueryError(f'Unknown table "{table_name}".')

    def get_all_tables(self) -> list[str]:
        return self._table_names + self._warehouse_table_names + self._view_table_names

    def get_posthog_tables(self) -> list[str]:
        return self._table_names

    def get_warehouse_tables(self) -> list[str]:
        return self._warehouse_table_names

    def get_views(self) -> list[str]:
        return self._view_table_names

    def add_warehouse_tables(self, **field_definitions: Any):
        for f_name, f_def in field_definitions.items():
            setattr(self, f_name, f_def)
            self._warehouse_table_names.append(f_name)

    def add_views(self, **field_definitions: Any):
        for f_name, f_def in field_definitions.items():
            setattr(self, f_name, f_def)
            self._view_table_names.append(f_name)


def _use_person_properties_from_events(database: Database) -> None:
    database.events.fields["person"] = FieldTraverser(chain=["poe"])


def _use_person_id_from_person_overrides(database: Database) -> None:
    database.events.fields["event_person_id"] = StringDatabaseField(name="person_id")
    database.events.fields["override"] = LazyJoin(
        from_field=["distinct_id"],
        join_table=PersonDistinctIdOverridesTable(),
        join_function=join_with_person_distinct_id_overrides_table,
    )
    database.events.fields["person_id"] = ExpressionField(
        name="person_id",
        expr=parse_expr(
            # NOTE: assumes `join_use_nulls = 0` (the default), as ``override.distinct_id`` is not Nullable
            "if(not(empty(override.distinct_id)), override.person_id, event_person_id)",
            start=None,
        ),
        isolate_scope=True,
    )


def _use_error_tracking_issue_id_from_error_tracking_issue_overrides(database: Database) -> None:
    database.events.fields["event_issue_id"] = ExpressionField(
        name="event_issue_id",
        # convert to UUID to match type of `issue_id` on overrides table
        expr=parse_expr("toUUID(properties.$exception_issue_id)"),
    )
    database.events.fields["exception_issue_override"] = LazyJoin(
        from_field=["fingerprint"],
        join_table=ErrorTrackingIssueFingerprintOverridesTable(),
        join_function=join_with_error_tracking_issue_fingerprint_overrides_table,
    )
    database.events.fields["issue_id"] = ExpressionField(
        name="issue_id",
        expr=parse_expr(
            # NOTE: assumes `join_use_nulls = 0` (the default), as ``override.fingerprint`` is not Nullable
            "if(not(empty(exception_issue_override.issue_id)), exception_issue_override.issue_id, event_issue_id)",
            start=None,
        ),
    )


def create_hogql_database(
    team_id: Optional[int] = None,
    *,
    team: Optional["Team"] = None,
    modifiers: Optional[HogQLQueryModifiers] = None,
    timings: Optional[HogQLTimings] = None,
) -> Database:
    from posthog.hogql.database.s3_table import S3Table
    from posthog.hogql.query import create_default_modifiers_for_team
    from posthog.models import Team
    from posthog.warehouse.models import (
        DataWarehouseJoin,
        DataWarehouseSavedQuery,
        DataWarehouseTable,
    )

    if timings is None:
        timings = HogQLTimings()

    with timings.measure("team"):
        if team_id is None and team is None:
            raise ValueError("Either team_id or team must be provided")

        if team is not None and team_id is not None and team.pk != team_id:
            raise ValueError("team_id and team must be the same")

        if team is None:
            team = Team.objects.get(pk=team_id)

        # Team is definitely not None at this point, make mypy believe that
        team = cast("Team", team)

    with timings.measure("modifiers"):
        modifiers = create_default_modifiers_for_team(team, modifiers)
        database = Database(timezone=team.timezone, week_start_day=team.week_start_day)

        if modifiers.personsOnEventsMode == PersonsOnEventsMode.DISABLED:
            # no change
            database.events.fields["person"] = FieldTraverser(chain=["pdi", "person"])
            database.events.fields["person_id"] = FieldTraverser(chain=["pdi", "person_id"])

        elif modifiers.personsOnEventsMode == PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS:
            database.events.fields["person_id"] = StringDatabaseField(name="person_id")
            _use_person_properties_from_events(database)

        elif modifiers.personsOnEventsMode == PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS:
            _use_person_id_from_person_overrides(database)
            _use_person_properties_from_events(database)
            cast(VirtualTable, database.events.fields["poe"]).fields["id"] = database.events.fields["person_id"]

        elif modifiers.personsOnEventsMode == PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_JOINED:
            _use_person_id_from_person_overrides(database)
            database.events.fields["person"] = LazyJoin(
                from_field=["person_id"],
                join_table=PersonsTable(),
                join_function=join_with_persons_table,
            )

        _use_error_tracking_issue_id_from_error_tracking_issue_overrides(database)

    with timings.measure("session_table"):
        if (
            modifiers.sessionTableVersion == SessionTableVersion.V2
            or modifiers.sessionTableVersion == SessionTableVersion.AUTO
        ):
            raw_sessions = RawSessionsTableV2()
            database.raw_sessions = raw_sessions
            sessions = SessionsTableV2()
            database.sessions = sessions
            events = database.events
            events.fields["session"] = LazyJoin(
                from_field=["$session_id"],
                join_table=sessions,
                join_function=join_events_table_to_sessions_table_v2,
            )
            replay_events = database.session_replay_events
            replay_events.fields["session"] = LazyJoin(
                from_field=["session_id"],
                join_table=sessions,
                join_function=join_replay_table_to_sessions_table_v2,
            )
            cast(LazyJoin, replay_events.fields["events"]).join_table = events
            raw_replay_events = database.raw_session_replay_events
            raw_replay_events.fields["session"] = LazyJoin(
                from_field=["session_id"],
                join_table=sessions,
                join_function=join_replay_table_to_sessions_table_v2,
            )
            cast(LazyJoin, raw_replay_events.fields["events"]).join_table = events

    with timings.measure("initial_domain_type"):
        database.persons.fields["$virt_initial_referring_domain_type"] = create_initial_domain_type(
            "$virt_initial_referring_domain_type", timings=timings
        )
    with timings.measure("initial_channel_type"):
        database.persons.fields["$virt_initial_channel_type"] = create_initial_channel_type(
            "$virt_initial_channel_type", modifiers.customChannelTypeRules, timings=timings
        )

    with timings.measure("group_type_mapping"):
        for mapping in GroupTypeMapping.objects.filter(project_id=team.project_id):
            if database.events.fields.get(mapping.group_type) is None:
                database.events.fields[mapping.group_type] = FieldTraverser(chain=[f"group_{mapping.group_type_index}"])

    warehouse_tables: dict[str, Table] = {}
    views: dict[str, Table] = {}

    with timings.measure("data_warehouse_saved_query"):
        with timings.measure("select"):
            saved_queries = list(DataWarehouseSavedQuery.objects.filter(team_id=team.pk).exclude(deleted=True))
        for saved_query in saved_queries:
            with timings.measure(f"saved_query_{saved_query.name}"):
                views[saved_query.name] = saved_query.hogql_definition(modifiers)

    with timings.measure("data_warehouse_tables"):
        with timings.measure("select"):
            tables = list(
                DataWarehouseTable.objects.filter(team_id=team.pk)
                .exclude(deleted=True)
                .select_related("credential", "external_data_source")
            )

        for table in tables:
            # Skip adding data warehouse tables that are materialized from views (in this case they have the same names)
            if views.get(table.name, None) is not None:
                continue

            with timings.measure(f"table_{table.name}"):
                s3_table = table.hogql_definition(modifiers)

                # If the warehouse table has no _properties_ field, then set it as a virtual table
                if s3_table.fields.get("properties") is None:

                    class WarehouseProperties(VirtualTable):
                        fields: dict[str, FieldOrTable] = s3_table.fields
                        parent_table: S3Table = s3_table

                        def to_printed_hogql(self):
                            return self.parent_table.to_printed_hogql()

                        def to_printed_clickhouse(self, context):
                            return self.parent_table.to_printed_clickhouse(context)

                    s3_table.fields["properties"] = WarehouseProperties(hidden=True)

                warehouse_tables[table.name] = s3_table

    def define_mappings(warehouse: dict[str, Table], get_table: Callable):
        if "id" not in warehouse[warehouse_modifier.table_name].fields.keys():
            warehouse[warehouse_modifier.table_name].fields["id"] = ExpressionField(
                name="id",
                expr=parse_expr(warehouse_modifier.id_field),
            )

        if "timestamp" not in warehouse[warehouse_modifier.table_name].fields.keys() or not isinstance(
            warehouse[warehouse_modifier.table_name].fields.get("timestamp"), DateTimeDatabaseField
        ):
            table_model = get_table(team=team, warehouse_modifier=warehouse_modifier)
            timestamp_field_type = table_model.get_clickhouse_column_type(warehouse_modifier.timestamp_field)

            # If field type is none or datetime, we can use the field directly
            if timestamp_field_type is None or timestamp_field_type.startswith("DateTime"):
                warehouse[warehouse_modifier.table_name].fields["timestamp"] = ExpressionField(
                    name="timestamp",
                    expr=ast.Field(chain=[warehouse_modifier.timestamp_field]),
                )
            else:
                warehouse[warehouse_modifier.table_name].fields["timestamp"] = ExpressionField(
                    name="timestamp",
                    expr=ast.Call(name="toDateTime", args=[ast.Field(chain=[warehouse_modifier.timestamp_field])]),
                )

        # TODO: Need to decide how the distinct_id and person_id fields are going to be handled
        if "distinct_id" not in warehouse[warehouse_modifier.table_name].fields.keys():
            warehouse[warehouse_modifier.table_name].fields["distinct_id"] = ExpressionField(
                name="distinct_id",
                expr=parse_expr(warehouse_modifier.distinct_id_field),
            )

        if "person_id" not in warehouse[warehouse_modifier.table_name].fields.keys():
            events_join = (
                DataWarehouseJoin.objects.filter(
                    team_id=team.pk,
                    source_table_name=warehouse_modifier.table_name,
                    joining_table_name="events",
                )
                .exclude(deleted=True)
                .first()
            )
            if events_join:
                warehouse[warehouse_modifier.table_name].fields["person_id"] = FieldTraverser(
                    chain=[events_join.field_name, "person_id"]
                )
            else:
                warehouse[warehouse_modifier.table_name].fields["person_id"] = ExpressionField(
                    name="person_id",
                    expr=parse_expr(warehouse_modifier.distinct_id_field),
                )

        return warehouse

    if modifiers.dataWarehouseEventsModifiers:
        for warehouse_modifier in modifiers.dataWarehouseEventsModifiers:
            # TODO: add all field mappings

            is_view = warehouse_modifier.table_name in views.keys()

            if is_view:
                views = define_mappings(
                    views,
                    lambda team, warehouse_modifier: DataWarehouseSavedQuery.objects.exclude(deleted=True)
                    .filter(team_id=team.pk, name=warehouse_modifier.table_name)
                    .latest("created_at"),
                )
            else:
                warehouse_tables = define_mappings(
                    warehouse_tables,
                    lambda team, warehouse_modifier: DataWarehouseTable.objects.exclude(deleted=True)
                    .filter(team_id=team.pk, name=warehouse_modifier.table_name)
                    .select_related("credential", "external_data_source")
                    .latest("created_at"),
                )

    database.add_warehouse_tables(**warehouse_tables)
    database.add_views(**views)

    with timings.measure("data_warehouse_joins"):
        for join in DataWarehouseJoin.objects.filter(team_id=team.pk).exclude(deleted=True):
            # Skip if either table is not present. This can happen if the table was deleted after the join was created.
            # User will be prompted on UI to resolve missing tables underlying the JOIN
            if not database.has_table(join.source_table_name) or not database.has_table(join.joining_table_name):
                continue

            try:
                source_table = database.get_table(join.source_table_name)
                joining_table = database.get_table(join.joining_table_name)

                field = parse_expr(join.source_table_key)
                if isinstance(field, ast.Field):
                    from_field = field.chain
                elif isinstance(field, ast.Call) and isinstance(field.args[0], ast.Field):
                    from_field = field.args[0].chain
                else:
                    raise ResolutionError("Data Warehouse Join HogQL expression should be a Field or Call node")

                field = parse_expr(join.joining_table_key)
                if isinstance(field, ast.Field):
                    to_field = field.chain
                elif isinstance(field, ast.Call) and isinstance(field.args[0], ast.Field):
                    to_field = field.args[0].chain
                else:
                    raise ResolutionError("Data Warehouse Join HogQL expression should be a Field or Call node")

                source_table.fields[join.field_name] = LazyJoin(
                    from_field=from_field,
                    to_field=to_field,
                    join_table=joining_table,
                    join_function=(
                        join.join_function_for_experiments()
                        if "events" == join.joining_table_name and join.configuration.get("experiments_optimized")
                        else join.join_function()
                    ),
                )

                if join.source_table_name == "persons":
                    person_field = database.events.fields["person"]
                    if isinstance(person_field, ast.FieldTraverser):
                        table_or_field: ast.FieldOrTable = database.events
                        for chain in person_field.chain:
                            if isinstance(table_or_field, ast.LazyJoin):
                                table_or_field = table_or_field.resolve_table(
                                    HogQLContext(team_id=team_id, database=database)
                                )
                                if table_or_field.has_field(chain):
                                    table_or_field = table_or_field.get_field(chain)
                                    if isinstance(table_or_field, ast.LazyJoin):
                                        table_or_field = table_or_field.resolve_table(
                                            HogQLContext(team_id=team_id, database=database)
                                        )
                            elif isinstance(table_or_field, ast.Table):
                                table_or_field = table_or_field.get_field(chain)

                        assert isinstance(table_or_field, ast.Table)

                        if isinstance(table_or_field, ast.VirtualTable):
                            table_or_field.fields[join.field_name] = ast.FieldTraverser(chain=["..", join.field_name])
                            database.events.fields[join.field_name] = LazyJoin(
                                from_field=from_field,
                                to_field=to_field,
                                join_table=joining_table,
                                # reusing join_function but with different source_table_key since we're joining 'directly' on events
                                join_function=join.join_function(
                                    override_source_table_key=f"person.{join.source_table_key}"
                                ),
                            )
                        else:
                            table_or_field.fields[join.field_name] = LazyJoin(
                                from_field=from_field,
                                to_field=to_field,
                                join_table=joining_table,
                                join_function=join.join_function(),
                            )
                    elif isinstance(person_field, ast.LazyJoin):
                        person_field.join_table.fields[join.field_name] = LazyJoin(  # type: ignore
                            from_field=from_field,
                            to_field=to_field,
                            join_table=joining_table,
                            join_function=join.join_function(),
                        )

            except Exception as e:
                capture_exception(e)

    return database


@dataclasses.dataclass
class SerializedField:
    key: str
    name: str
    type: DatabaseSerializedFieldType
    schema_valid: bool
    fields: Optional[list[str]] = None
    table: Optional[str] = None
    chain: Optional[list[str | int]] = None


DatabaseSchemaTable: TypeAlias = DatabaseSchemaPostHogTable | DatabaseSchemaDataWarehouseTable | DatabaseSchemaViewTable


def serialize_database(
    context: HogQLContext,
) -> dict[str, DatabaseSchemaTable]:
    from posthog.warehouse.models.datawarehouse_saved_query import DataWarehouseSavedQuery

    tables: dict[str, DatabaseSchemaTable] = {}

    if context.database is None:
        raise ResolutionError("Must provide database to serialize_database")

    if context.team_id is None:
        raise ResolutionError("Must provide team_id to serialize_database")

    # PostHog Tables
    posthog_tables = context.database.get_posthog_tables()
    for table_key in posthog_tables:
        field_input: dict[str, Any] = {}
        table = getattr(context.database, table_key, None)
        if isinstance(table, FunctionCallTable):
            field_input = table.get_asterisk()
        elif isinstance(table, Table):
            field_input = table.fields

        fields = serialize_fields(field_input, context, table_key, table_type="posthog")
        fields_dict = {field.name: field for field in fields}
        tables[table_key] = DatabaseSchemaPostHogTable(fields=fields_dict, id=table_key, name=table_key)

    # Data Warehouse Tables and Views - Fetch all related data in one go
    warehouse_table_names = context.database.get_warehouse_tables()
    views = context.database.get_views()

    # Fetch warehouse tables with related data in a single query
    warehouse_tables_with_data = (
        DataWarehouseTable.objects.select_related("credential", "external_data_source")
        .prefetch_related(
            "externaldataschema_set",
            Prefetch(
                "external_data_source__jobs",
                queryset=ExternalDataJob.objects.filter(status="Completed", team_id=context.team_id).order_by(
                    "-created_at"
                )[:1],
                to_attr="latest_completed_job",
            ),
        )
        .filter(Q(deleted=False) | Q(deleted__isnull=True), team_id=context.team_id, name__in=warehouse_table_names)
        .order_by("external_data_source__prefix", "external_data_source__source_type", "name")
        .all()
        if warehouse_table_names
        else []
    )

    # Fetch all views in a single query
    all_views = (
        DataWarehouseSavedQuery.objects.exclude(deleted=True).filter(team_id=context.team_id).all() if views else []
    )

    # Process warehouse tables
    for warehouse_table in warehouse_tables_with_data:
        table_key = warehouse_table.name

        field_input = {}
        table = getattr(context.database, table_key, None)
        if isinstance(table, Table):
            field_input = table.fields

        fields = serialize_fields(field_input, context, table_key, warehouse_table.columns, table_type="external")
        fields_dict = {field.name: field for field in fields}

        # Get schema from prefetched data
        schema_data = list(warehouse_table.externaldataschema_set.all())
        if not schema_data:
            schema = None
        else:
            db_schema = schema_data[0]
            schema = DatabaseSchemaSchema(
                id=str(db_schema.id),
                name=db_schema.name,
                should_sync=db_schema.should_sync,
                incremental=db_schema.is_incremental,
                status=db_schema.status,
                last_synced_at=str(db_schema.last_synced_at),
            )

        # Get source from prefetched data
        if warehouse_table.external_data_source is None:
            source = None
        else:
            db_source = warehouse_table.external_data_source
            latest_completed_run = (
                db_source.latest_completed_job[0]
                if hasattr(db_source, "latest_completed_job") and db_source.latest_completed_job
                else None
            )
            source = DatabaseSchemaSource(
                id=str(db_source.source_id),
                status=db_source.status,
                source_type=db_source.source_type,
                prefix=db_source.prefix or "",
                last_synced_at=str(latest_completed_run.created_at) if latest_completed_run else None,
            )

        tables[table_key] = DatabaseSchemaDataWarehouseTable(
            fields=fields_dict,
            id=str(warehouse_table.id),
            name=table_key,
            format=warehouse_table.format,
            url_pattern=warehouse_table.url_pattern,
            schema=schema,
            source=source,
        )

    # Process views using prefetched data
    views_dict = {view.name: view for view in all_views}
    for view_name in views:
        view: SavedQuery | None = getattr(context.database, view_name, None)
        if view is None:
            continue

        fields = serialize_fields(view.fields, context, view_name, table_type="external")
        fields_dict = {field.name: field for field in fields}

        saved_query = views_dict.get(view_name)
        if saved_query:
            tables[view_name] = DatabaseSchemaViewTable(
                fields=fields_dict,
                id=str(saved_query.pk),
                name=view.name,
                query=HogQLQuery(query=saved_query.query["query"]),
            )

    return tables


def constant_type_to_serialized_field_type(constant_type: ast.ConstantType) -> DatabaseSerializedFieldType | None:
    if isinstance(constant_type, ast.StringType):
        return DatabaseSerializedFieldType.STRING
    if isinstance(constant_type, ast.BooleanType):
        return DatabaseSerializedFieldType.BOOLEAN
    if isinstance(constant_type, ast.DateType):
        return DatabaseSerializedFieldType.DATE
    if isinstance(constant_type, ast.DateTimeType):
        return DatabaseSerializedFieldType.DATETIME
    if isinstance(constant_type, ast.UUIDType):
        return DatabaseSerializedFieldType.STRING
    if isinstance(constant_type, ast.ArrayType):
        return DatabaseSerializedFieldType.ARRAY
    if isinstance(constant_type, ast.TupleType):
        return DatabaseSerializedFieldType.JSON
    if isinstance(constant_type, ast.IntegerType):
        return DatabaseSerializedFieldType.INTEGER
    if isinstance(constant_type, ast.FloatType):
        return DatabaseSerializedFieldType.FLOAT
    return None


HOGQL_CHARACTERS_TO_BE_WRAPPED = ["@", "-", "!", "$", "+"]


def serialize_fields(
    field_input,
    context: HogQLContext,
    table_name: str,
    db_columns: Optional[DataWarehouseTableColumns] = None,
    table_type: Literal["posthog"] | Literal["external"] = "posthog",
) -> list[DatabaseSchemaField]:
    from posthog.hogql.database.models import SavedQuery
    from posthog.hogql.resolver import resolve_types_from_table

    field_output: list[DatabaseSchemaField] = []
    for field_key, field in field_input.items():
        try:
            if db_columns is not None:
                column = db_columns[field_key]
                if isinstance(column, str):
                    schema_valid = True
                else:
                    schema_valid = cast(bool, column.get("valid", True))
            else:
                schema_valid = True
        except KeyError:
            # We redefine fields on some sourced tables, causing the "hogql" and "clickhouse" field names to be intentionally out of sync
            schema_valid = True

        if any(n in field_key for n in HOGQL_CHARACTERS_TO_BE_WRAPPED):
            hogql_value = f"`{field_key}`"
        else:
            hogql_value = str(field_key)

        if isinstance(field, FieldOrTable):
            if field.hidden:
                continue

        if field_key == "team_id" and table_type == "posthog":
            pass
        elif isinstance(field, DatabaseField):
            if isinstance(field, IntegerDatabaseField):
                field_output.append(
                    DatabaseSchemaField(
                        name=field_key,
                        hogql_value=hogql_value,
                        type=DatabaseSerializedFieldType.INTEGER,
                        schema_valid=schema_valid,
                    )
                )
            elif isinstance(field, FloatDatabaseField):
                field_output.append(
                    DatabaseSchemaField(
                        name=field_key,
                        hogql_value=hogql_value,
                        type=DatabaseSerializedFieldType.FLOAT,
                        schema_valid=schema_valid,
                    )
                )
            elif isinstance(field, StringDatabaseField):
                field_output.append(
                    DatabaseSchemaField(
                        name=field_key,
                        hogql_value=hogql_value,
                        type=DatabaseSerializedFieldType.STRING,
                        schema_valid=schema_valid,
                    )
                )
            elif isinstance(field, DateTimeDatabaseField):
                field_output.append(
                    DatabaseSchemaField(
                        name=field_key,
                        hogql_value=hogql_value,
                        type=DatabaseSerializedFieldType.DATETIME,
                        schema_valid=schema_valid,
                    )
                )
            elif isinstance(field, DateDatabaseField):
                field_output.append(
                    DatabaseSchemaField(
                        name=field_key,
                        hogql_value=hogql_value,
                        type=DatabaseSerializedFieldType.DATE,
                        schema_valid=schema_valid,
                    )
                )
            elif isinstance(field, BooleanDatabaseField):
                field_output.append(
                    DatabaseSchemaField(
                        name=field_key,
                        hogql_value=hogql_value,
                        type=DatabaseSerializedFieldType.BOOLEAN,
                        schema_valid=schema_valid,
                    )
                )
            elif isinstance(field, StringJSONDatabaseField):
                field_output.append(
                    DatabaseSchemaField(
                        name=field_key,
                        hogql_value=hogql_value,
                        type=DatabaseSerializedFieldType.JSON,
                        schema_valid=schema_valid,
                    )
                )
            elif isinstance(field, StringArrayDatabaseField):
                field_output.append(
                    DatabaseSchemaField(
                        name=field_key,
                        hogql_value=hogql_value,
                        type=DatabaseSerializedFieldType.ARRAY,
                        schema_valid=schema_valid,
                    )
                )
            elif isinstance(field, ExpressionField):
                field_expr = resolve_types_from_table(field.expr, table_name, context, "hogql")
                assert field_expr.type is not None
                constant_type = field_expr.type.resolve_constant_type(context)

                field_type = constant_type_to_serialized_field_type(constant_type)
                if field_type is None:
                    field_type = DatabaseSerializedFieldType.EXPRESSION

                field_output.append(
                    DatabaseSchemaField(
                        name=field_key,
                        hogql_value=hogql_value,
                        type=field_type,
                        schema_valid=schema_valid,
                    )
                )
        elif isinstance(field, LazyJoin):
            resolved_table = field.resolve_table(context)

            if isinstance(resolved_table, SavedQuery):
                type = DatabaseSerializedFieldType.VIEW
                id = str(resolved_table.id)
            else:
                type = DatabaseSerializedFieldType.LAZY_TABLE
                id = None

            field_output.append(
                DatabaseSchemaField(
                    name=field_key,
                    hogql_value=hogql_value,
                    type=type,
                    schema_valid=schema_valid,
                    table=field.resolve_table(context).to_printed_hogql(),
                    fields=list(field.resolve_table(context).fields.keys()),
                    id=id or field_key,
                )
            )
        elif isinstance(field, VirtualTable):
            field_output.append(
                DatabaseSchemaField(
                    name=field_key,
                    hogql_value=hogql_value,
                    type=DatabaseSerializedFieldType.VIRTUAL_TABLE,
                    schema_valid=schema_valid,
                    table=field.to_printed_hogql(),
                    fields=list(field.fields.keys()),
                )
            )
        elif isinstance(field, FieldTraverser):
            field_output.append(
                DatabaseSchemaField(
                    name=field_key,
                    hogql_value=hogql_value,
                    type=DatabaseSerializedFieldType.FIELD_TRAVERSER,
                    schema_valid=schema_valid,
                    chain=field.chain,
                )
            )
    return field_output
