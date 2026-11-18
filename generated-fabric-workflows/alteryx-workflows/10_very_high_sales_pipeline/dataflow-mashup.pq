section Section1;

shared valid_rows = let
    raw_orders = #table({"CustomerID", "Region", "Channel", "OrderDate", "SKU", "Amount", "Units"}, {{"C001", "West", "Online", "2026-01-12", "SKU-A-100", "1200", "4"}, {"C002", "East", "Store", "2026-01-18", "SKU-B-220", "840", "2"}, {"C001", "West", "Online", "2026-02-03", "SKU-A-140", "640", "1"}, {"C003", "North", "Partner", "2026-02-11", "SKU-C-010", "2100", "6"}, {"C004", "South", "Store", "2026-03-01", "SKU-B-220", "430", "3"}, {"C002", "East", "Online", "2026-03-09", "SKU-A-100", "990", "2"}, {"C005", "West", "Partner", "2026-03-21", "SKU-C-010", "150", "1"}, {"C003", "North", "Store", "2026-04-02", "SKU-A-140", "1760", "5"}}),
    sku_parts_1 = Table.AddColumn(raw_orders, "SKUFamily", each Text.BeforeDelimiter(Text.Upper(Text.From(Record.Field(_, "SKU"))), "-"), type text),
    sku_parts = Table.AddColumn(sku_parts_1, "SKUNumber", each Text.AfterDelimiter(Text.Upper(Text.From(Record.Field(_, "SKU"))), "-"), type text),
    order_date = Table.AddColumn(sku_parts, "OrderDateParsed", each Date.FromText(Text.From(Record.Field(_, "OrderDate")), [Format = "yyyy-MM-dd"]), type date),
    amount = Table.AddColumn(order_date, "AmountNum", each Number.From(Record.Field(_, "Amount"))),
    units = Table.AddColumn(amount, "UnitsNum", each Number.From(Record.Field(_, "Units"))),
    quality_flag = Table.AddColumn(units, "QualityFlag", each if Record.Field(_, "AmountNum") = null or (Record.Field(_, "AmountNum") < 0) then "Invalid" else "Valid"),
    valid_rows = Table.SelectRows(quality_flag, each Record.Field(_, "QualityFlag") = "Valid")
in
    valid_rows;

shared rejected = valid_rows;

shared dim_unique = let
    customer_dim = #table({"CustomerID", "CustomerName", "Tier"}, {{"C001", "Acme Retail", "Gold"}, {"C002", "Northwind", "Silver"}, {"C003", "Contoso", "Gold"}, {"C004", "Fabrikam", "Bronze"}, {"C005", "Adventure", "Silver"}}),
    dim_unique = Table.Distinct(customer_dim, {"CustomerID"})
in
    dim_unique;

shared running_amount = let
    fact_to_dim_Joined = Table.NestedJoin(valid_rows, {"CustomerID"}, dim_unique, {"CustomerID"}, "__right", JoinKind.Inner),
    fact_to_dim_RightColumns = List.RemoveItems(Table.ColumnNames(dim_unique), {"CustomerID"}),
    fact_to_dim_OutputColumns = List.Transform(fact_to_dim_RightColumns, each if List.Contains(Table.ColumnNames(valid_rows), _) then _ & "_Right" else _),
    fact_to_dim = Table.ExpandTableColumn(fact_to_dim_Joined, "__right", fact_to_dim_RightColumns, fact_to_dim_OutputColumns),
    loyalty = Table.AddColumn(fact_to_dim, "LoyaltyCredit", each if Record.Field(_, "Tier") = "Gold" then Record.Field(_, "AmountNum") * 0.05 else if Record.Field(_, "Tier") = "Silver" then Record.Field(_, "AmountNum") * 0.02 else 0),
    time_order = Table.Sort(loyalty, {{"OrderDate", Order.Ascending}}),
    running_amount_Grouped = Table.Group(time_order, {"Region"}, {{{"__rows", (groupTable) => let Indexed = Table.AddIndexColumn(groupTable, "__row_index", 0, 1, Int64.Type), Running = Table.AddColumn(Indexed, "RunningTotal", each List.Sum(List.FirstN(Table.Column(Indexed, "Amount"), Record.Field(_, "__row_index") + 1)), type number) in Table.RemoveColumns(Running, {"__row_index"}), type table}}}),
    running_amount = Table.Combine(Table.Column(running_amount_Grouped, "__rows"))
in
    running_amount;

shared by_region = let
    by_region = Table.Group(running_amount, {"Region"}, {{"Sum_AmountNum", each List.Sum(List.Transform([AmountNum], Number.From)), type number}, {"RowCount", each Table.RowCount(_), type number}})
in
    by_region;

shared by_channel = let
    by_channel = Table.Group(running_amount, {"Channel"}, {{"Sum_AmountNum", each List.Sum(List.Transform([AmountNum], Number.From)), type number}, {"RowCount", each Table.RowCount(_), type number}})
in
    by_channel;

shared target = let
    targets = #table({"Region", "TargetAmount"}, {{"West", "5000"}, {"East", "3000"}, {"North", "4000"}, {"South", "2000"}}),
    target = Table.AddColumn(targets, "TargetAmount", each Number.From(Record.Field(_, "TargetAmount")))
in
    target;

shared goal_status = let
    region_vs_target_Joined = Table.NestedJoin(by_region, {"Region"}, target, {"Region"}, "__right", JoinKind.Inner),
    region_vs_target_RightColumns = List.RemoveItems(Table.ColumnNames(target), {"Region"}),
    region_vs_target_OutputColumns = List.Transform(region_vs_target_RightColumns, each if List.Contains(Table.ColumnNames(by_region), _) then _ & "_Right" else _),
    region_vs_target = Table.ExpandTableColumn(region_vs_target_Joined, "__right", region_vs_target_RightColumns, region_vs_target_OutputColumns),
    gap = Table.AddColumn(region_vs_target, "Gap", each Record.Field(_, "Sum_AmountNum") - Record.Field(_, "TargetAmount")),
    goal_status = Table.AddColumn(gap, "GoalStatus", each if Record.Field(_, "Gap") >= 0 then "Met" else "Missed")
in
    goal_status;

shared publish_stack = let
    publish_stack = Table.Combine({by_region, by_channel})
in
    publish_stack;

shared top_gaps = let
    worst_gap = Table.Sort(goal_status, {{"Gap", Order.Descending}}),
    top_gaps = Table.FirstN(worst_gap, 10)
in
    top_gaps;

shared goal_status_29 = goal_status;

shared channel_matrix_30 = let
    channel_matrix_Source = Table.SelectColumns(by_channel, {"Region", "Channel", "Amount"}),
    channel_matrix = Table.Pivot(channel_matrix_Source, List.Distinct(Table.Column(channel_matrix_Source, "Channel")), "Channel", "Amount", each List.Sum(List.Transform(_, Number.From)))
in
    channel_matrix;

shared sku_family = let
    by_sku_family = Table.Group(running_amount, {"SKUFamily"}, {{"Sum_UnitsNum", each List.Sum(List.Transform([UnitsNum], Number.From)), type number}, {"RowCount", each Table.RowCount(_), type number}})
in
    by_sku_family;

shared enriched_facts = running_amount;
