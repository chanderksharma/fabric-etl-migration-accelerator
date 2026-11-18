section Section1;

shared clean_orders = let
    orders = #table({"CustomerID", "Region", "Channel", "OrderDate", "SKU", "Amount", "Units"}, {{"C001", "West", "Online", "2026-01-12", "SKU-A-100", "1200", "4"}, {"C002", "East", "Store", "2026-01-18", "SKU-B-220", "840", "2"}, {"C001", "West", "Online", "2026-02-03", "SKU-A-140", "640", "1"}, {"C003", "North", "Partner", "2026-02-11", "SKU-C-010", "2100", "6"}, {"C004", "South", "Store", "2026-03-01", "SKU-B-220", "430", "3"}, {"C002", "East", "Online", "2026-03-09", "SKU-A-100", "990", "2"}, {"C005", "West", "Partner", "2026-03-21", "SKU-C-010", "150", "1"}, {"C003", "North", "Store", "2026-04-02", "SKU-A-140", "1760", "5"}}),
    amount_as_number = Table.AddColumn(orders, "AmountNum", each Number.From(Record.Field(_, "Amount"))),
    largest_first = Table.Sort(amount_as_number, {{"AmountNum", Order.Descending}})
in
    largest_first;
