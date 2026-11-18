section Section1;

shared tag_online = let
    online_orders = #table({"CustomerID", "Region", "Channel", "OrderDate", "SKU", "Amount", "Units"}, {{"C001", "West", "Online", "2026-01-12", "SKU-A-100", "1200", "4"}, {"C001", "West", "Online", "2026-02-03", "SKU-A-140", "640", "1"}, {"C002", "East", "Online", "2026-03-09", "SKU-A-100", "990", "2"}}),
    tag_online = Table.AddColumn(online_orders, "SourceStream", each "Online")
in
    tag_online;

shared tag_other = let
    other_channels = #table({"CustomerID", "Region", "Channel", "OrderDate", "SKU", "Amount", "Units"}, {{"C002", "East", "Store", "2026-01-18", "SKU-B-220", "840", "2"}, {"C003", "North", "Partner", "2026-02-11", "SKU-C-010", "2100", "6"}, {"C004", "South", "Store", "2026-03-01", "SKU-B-220", "430", "3"}, {"C005", "West", "Partner", "2026-03-21", "SKU-C-010", "150", "1"}, {"C003", "North", "Store", "2026-04-02", "SKU-A-140", "1760", "5"}}),
    tag_other = Table.AddColumn(other_channels, "SourceStream", each "Other")
in
    tag_other;

shared channel_crosstab = let
    stack_channels = Table.Combine({tag_online, tag_other}),
    amount_number = Table.AddColumn(stack_channels, "AmountNum", each Number.From(Record.Field(_, "Amount"))),
    amount_by_channel_Source = Table.SelectColumns(amount_number, {"Region", "Channel", "Amount"}),
    amount_by_channel = Table.Pivot(amount_by_channel_Source, List.Distinct(Table.Column(amount_by_channel_Source, "Channel")), "Channel", "Amount", each List.Sum(List.Transform(_, Number.From)))
in
    amount_by_channel;
