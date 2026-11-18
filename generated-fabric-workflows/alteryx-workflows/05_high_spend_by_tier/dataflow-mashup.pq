section Section1;

shared customers = let
    customers = #table({"CustomerID", "CustomerName", "Tier"}, {{"C001", "Acme Retail", "Gold"}, {"C002", "Northwind", "Silver"}, {"C003", "Contoso", "Gold"}, {"C004", "Fabrikam", "Bronze"}, {"C005", "Adventure", "Silver"}})
in
    customers;

shared units_number = let
    orders = #table({"CustomerID", "Region", "Channel", "OrderDate", "SKU", "Amount", "Units"}, {{"C001", "West", "Online", "2026-01-12", "SKU-A-100", "1200", "4"}, {"C002", "East", "Store", "2026-01-18", "SKU-B-220", "840", "2"}, {"C001", "West", "Online", "2026-02-03", "SKU-A-140", "640", "1"}, {"C003", "North", "Partner", "2026-02-11", "SKU-C-010", "2100", "6"}, {"C004", "South", "Store", "2026-03-01", "SKU-B-220", "430", "3"}, {"C002", "East", "Online", "2026-03-09", "SKU-A-100", "990", "2"}, {"C005", "West", "Partner", "2026-03-21", "SKU-C-010", "150", "1"}, {"C003", "North", "Store", "2026-04-02", "SKU-A-140", "1760", "5"}}),
    amount_number = Table.AddColumn(orders, "AmountNum", each Number.From(Record.Field(_, "Amount"))),
    units_number = Table.AddColumn(amount_number, "UnitsNum", each Number.From(Record.Field(_, "Units")))
in
    units_number;

shared orders_to_customers = let
    orders_to_customers_Joined = Table.NestedJoin(units_number, {"CustomerID"}, customers, {"CustomerID"}, "__right", JoinKind.Inner),
    orders_to_customers_RightColumns = List.RemoveItems(Table.ColumnNames(customers), {"CustomerID"}),
    orders_to_customers_OutputColumns = List.Transform(orders_to_customers_RightColumns, each if List.Contains(Table.ColumnNames(units_number), _) then _ & "_Right" else _),
    orders_to_customers = Table.ExpandTableColumn(orders_to_customers_Joined, "__right", orders_to_customers_RightColumns, orders_to_customers_OutputColumns)
in
    orders_to_customers;

shared spend_by_tier_8 = let
    spend_by_tier = Table.Group(orders_to_customers, {"Tier"}, {{"Sum_AmountNum", each List.Sum(List.Transform([AmountNum], Number.From)), type number}, {"RowCount", each Table.RowCount(_), type number}}),
    rank_tiers = Table.Sort(spend_by_tier, {{"Sum_AmountNum", Order.Descending}})
in
    rank_tiers;

shared left_unmatched = orders_to_customers;
