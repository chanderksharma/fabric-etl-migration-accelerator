section Section1;

shared running_total_by_region = let
    orders = #table({"CustomerID", "Region", "Channel", "OrderDate", "SKU", "Amount", "Units"}, {{"C001", "West", "Online", "2026-01-12", "SKU-A-100", "1200", "4"}, {"C002", "East", "Store", "2026-01-18", "SKU-B-220", "840", "2"}, {"C001", "West", "Online", "2026-02-03", "SKU-A-140", "640", "1"}, {"C003", "North", "Partner", "2026-02-11", "SKU-C-010", "2100", "6"}, {"C004", "South", "Store", "2026-03-01", "SKU-B-220", "430", "3"}, {"C002", "East", "Online", "2026-03-09", "SKU-A-100", "990", "2"}, {"C005", "West", "Partner", "2026-03-21", "SKU-C-010", "150", "1"}, {"C003", "North", "Store", "2026-04-02", "SKU-A-140", "1760", "5"}}),
    numeric_amount = Table.AddColumn(orders, "Amount", each Number.From(Record.Field(_, "Amount"))),
    chronological = Table.Sort(numeric_amount, {{"OrderDate", Order.Ascending}}),
    running_total_by_region_Grouped = Table.Group(chronological, {"Region"}, {{{"__rows", (groupTable) => let Indexed = Table.AddIndexColumn(groupTable, "__row_index", 0, 1, Int64.Type), Running = Table.AddColumn(Indexed, "RunningTotal", each List.Sum(List.FirstN(Table.Column(Indexed, "Amount"), Record.Field(_, "__row_index") + 1)), type number) in Table.RemoveColumns(Running, {"__row_index"}), type table}}}),
    running_total_by_region = Table.Combine(Table.Column(running_total_by_region_Grouped, "__rows"))
in
    running_total_by_region;

shared region_totals = let
    region_totals = Table.Group(running_total_by_region, {"Region"}, {{"Sum_Amount", each List.Sum(List.Transform([Amount], Number.From)), type number}, {"RowCount", each Table.RowCount(_), type number}})
in
    region_totals;

shared numeric_target = let
    targets = #table({"Region", "TargetAmount"}, {{"West", "5000"}, {"East", "3000"}, {"North", "4000"}, {"South", "2000"}}),
    numeric_target = Table.AddColumn(targets, "TargetAmount", each Number.From(Record.Field(_, "TargetAmount")))
in
    numeric_target;

shared variance_11 = let
    actual_vs_target_Joined = Table.NestedJoin(region_totals, {"Region"}, numeric_target, {"Region"}, "__right", JoinKind.Inner),
    actual_vs_target_RightColumns = List.RemoveItems(Table.ColumnNames(numeric_target), {"Region"}),
    actual_vs_target_OutputColumns = List.Transform(actual_vs_target_RightColumns, each if List.Contains(Table.ColumnNames(region_totals), _) then _ & "_Right" else _),
    actual_vs_target = Table.ExpandTableColumn(actual_vs_target_Joined, "__right", actual_vs_target_RightColumns, actual_vs_target_OutputColumns),
    variance = Table.AddColumn(actual_vs_target, "Variance", each Record.Field(_, "Sum_Amount") - Record.Field(_, "TargetAmount")),
    status = Table.AddColumn(variance, "Status", each if Record.Field(_, "Variance") >= 0 then "Above" else "Below")
in
    status;

shared running_totals = running_total_by_region;
