section Section1;

shared match_key_a = let
    batch_a = #table({"CustomerID", "Region", "Channel", "OrderDate", "SKU", "Amount", "Units"}, {{"C001", "West", "Online", "2026-01-12", "SKU-A-100", "1200", "4"}, {"C002", "East", "Store", "2026-01-18", "SKU-B-220", "840", "2"}, {"C001", "West", "Online", "2026-02-03", "SKU-A-140", "640", "1"}, {"C003", "North", "Partner", "2026-02-11", "SKU-C-010", "2100", "6"}, {"C004", "South", "Store", "2026-03-01", "SKU-B-220", "430", "3"}, {"C002", "East", "Online", "2026-03-09", "SKU-A-100", "990", "2"}, {"C005", "West", "Partner", "2026-03-21", "SKU-C-010", "150", "1"}, {"C003", "North", "Store", "2026-04-02", "SKU-A-140", "1760", "5"}}),
    batch_a_id = Table.AddIndexColumn(batch_a, "RecordID", 1, 1, Int64.Type),
    region_key_a = Table.AddColumn(batch_a_id, "RegionKey", each Text.Upper(Text.From(Record.Field(_, "Region")))),
    match_key_a = Table.AddColumn(region_key_a, "MatchKey", each Text.Combine({Text.From(Record.Field(_, "CustomerID")), Text.From(Record.Field(_, "SKU")), Text.From(Record.Field(_, "OrderDate"))}, "|"))
in
    match_key_a;

shared match_key_b = let
    batch_b = #table({"CustomerID", "Region", "Channel", "OrderDate", "SKU", "Amount", "Units"}, {{"C003", "North", "Store", "2026-04-02", "SKU-A-140", "1760", "5"}, {"C005", "West", "Partner", "2026-03-21", "SKU-C-010", "150", "1"}, {"C002", "East", "Online", "2026-03-09", "SKU-A-100", "990", "2"}, {"C004", "South", "Store", "2026-03-01", "SKU-B-220", "430", "3"}, {"C003", "North", "Partner", "2026-02-11", "SKU-C-010", "2100", "6"}, {"C001", "West", "Online", "2026-02-03", "SKU-A-140", "640", "1"}, {"C002", "East", "Store", "2026-01-18", "SKU-B-220", "840", "2"}, {"C001", "West", "Online", "2026-01-12", "SKU-A-100", "1200", "4"}}),
    batch_b_id = Table.AddIndexColumn(batch_b, "RecordID", 1, 1, Int64.Type),
    region_key_b = Table.AddColumn(batch_b_id, "RegionKey", each Text.Upper(Text.From(Record.Field(_, "Region")))),
    match_key_b = Table.AddColumn(region_key_b, "MatchKey", each Text.Combine({Text.From(Record.Field(_, "CustomerID")), Text.From(Record.Field(_, "SKU")), Text.From(Record.Field(_, "OrderDate"))}, "|"))
in
    match_key_b;

shared reconcile_batches = let
    reconcile_batches_Joined = Table.NestedJoin(match_key_a, {"MatchKey"}, match_key_b, {"MatchKey"}, "__right", JoinKind.Inner),
    reconcile_batches_RightColumns = List.RemoveItems(Table.ColumnNames(match_key_b), {"MatchKey"}),
    reconcile_batches_OutputColumns = List.Transform(reconcile_batches_RightColumns, each if List.Contains(Table.ColumnNames(match_key_a), _) then _ & "_Right" else _),
    reconcile_batches = Table.ExpandTableColumn(reconcile_batches_Joined, "__right", reconcile_batches_RightColumns, reconcile_batches_OutputColumns)
in
    reconcile_batches;

shared amount_delta = let
    amount_delta = Table.AddColumn(reconcile_batches, "AmountDelta", each Number.From(Record.Field(_, "Left_Amount")) - Number.From(Record.Field(_, "Right_Amount")))
in
    amount_delta;

shared left_only_keys = let
    left_only_keys = Table.Distinct(reconcile_batches, {"MatchKey"})
in
    left_only_keys;

shared right_only_keys = let
    right_only_keys = Table.Distinct(reconcile_batches, {"MatchKey"})
in
    right_only_keys;

shared deltas = let
    changed_amounts = Table.SelectRows(amount_delta, each Record.Field(_, "AmountDelta") <> "0"),
    delta_by_region = Table.Group(changed_amounts, {"Left_Region"}, {{"Sum_AmountDelta", each List.Sum(List.Transform([AmountDelta], Number.From)), type number}, {"RowCount", each Table.RowCount(_), type number}})
in
    delta_by_region;

shared exceptions_19 = let
    exceptions = Table.Combine({left_only_keys, right_only_keys}),
    sort_exceptions = Table.Sort(exceptions, {{"MatchKey", Order.Ascending}}),
    exception_sample = Table.FirstN(sort_exceptions, 20)
in
    exception_sample;

shared matched = amount_delta;
