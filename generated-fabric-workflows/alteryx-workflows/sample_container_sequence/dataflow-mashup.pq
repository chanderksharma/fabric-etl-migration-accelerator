section Section1;

shared SourceBindings = error "Configure source bindings before refresh";

shared positive_amounts = let
    orders = Record.Field(SourceBindings, "1"),
    keep_order_fields = Table.SelectColumns(orders, {"OrderID", "CustomerID", "SKU", "Amount", "Units"}),
    amount_and_units_1 = Table.AddColumn(keep_order_fields, "AmountNum", each Number.From(Record.Field(_, "Amount"))),
    amount_and_units_2 = Table.AddColumn(amount_and_units_1, "UnitsNum", each Number.From(Record.Field(_, "Units"))),
    positive_amounts = Table.SelectRows(amount_and_units_2, each Record.Field(_, "AmountNum") > 0)
in
    positive_amounts;

shared active_customers = let
    customers = Record.Field(SourceBindings, "5"),
    keep_customer_fields = Table.SelectColumns(customers, {"CustomerID", "CustomerName", "Tier", "Status"}),
    active_customers = Table.SelectRows(keep_customer_fields, each Record.Field(_, "Status") = "Active")
in
    active_customers;

shared matched_orders = let
    match_on_customer_Joined = Table.NestedJoin(positive_amounts, {"CustomerID"}, active_customers, {"CustomerID"}, "__right", JoinKind.Inner),
    match_on_customer_RightColumns = List.RemoveItems(Table.ColumnNames(active_customers), {"CustomerID"}),
    match_on_customer_OutputColumns = List.Transform(match_on_customer_RightColumns, each if List.Contains(Table.ColumnNames(positive_amounts), _) then _ & "_Right" else _),
    match_on_customer = Table.ExpandTableColumn(match_on_customer_Joined, "__right", match_on_customer_RightColumns, match_on_customer_OutputColumns),
    line_value = Table.AddColumn(match_on_customer, "LineValue", each Record.Field(_, "AmountNum") * Record.Field(_, "UnitsNum"))
in
    line_value;
