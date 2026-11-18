section Section1;

shared SourceBindings = error "Configure source bindings before refresh";

shared orderscurated = let
    orders = Record.Field(SourceBindings, "Orders"),
    flt_valid = Table.SelectRows(orders, each Record.Field(_, "Amount") > 0)
in
    flt_valid;
