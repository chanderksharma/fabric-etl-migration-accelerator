section Section1;

shared SourceBindings = error "Configure source bindings before refresh";

shared exp_date_validation = let
    ledger_src_file = Record.Field(SourceBindings, "Ledger_Src_File"),
    exp_date_validation_1 = Table.AddColumn(ledger_src_file, "File_Name", each Text.Trim(Text.From(Record.Field(_, "CurrentlyProcessedFileName")))),
    exp_date_validation_2 = Table.AddColumn(exp_date_validation_1, "CHANNEL", each if Record.Field(_, "AccountGroup") = "NORTH_REGION" then "NORTH" else "SOUTH"),
    exp_date_validation = Table.AddColumn(exp_date_validation_2, "REJECT_REASON", each if Record.Field(_, "AccountGroup") = null then "Missing AccountGroup" else null)
in
    exp_date_validation;

shared rtr_ledger_default1 = let
    rtr_ledger_default1 = Table.SelectRows(exp_date_validation, each not ((Record.Field(_, "REJECT_REASON") = null) or ((Record.Field(_, "REJECT_REASON") <> null) and (Record.Field(_, "CHANNEL") = "NORTH")) or ((Record.Field(_, "REJECT_REASON") <> null) and (Record.Field(_, "CHANNEL") = "SOUTH"))))
in
    rtr_ledger_default1;

shared stg_ledger_content = let
    rtr_ledger_stg_data_alias1 = Table.AddColumn(exp_date_validation, "AccountGroup1", each Record.Field(_, "AccountGroup")),
    rtr_ledger_stg_data_alias2 = Table.AddColumn(rtr_ledger_stg_data_alias1, "Balance1", each Record.Field(_, "Balance")),
    rtr_ledger_stg_data_alias3 = Table.AddColumn(rtr_ledger_stg_data_alias2, "File_Name1", each Record.Field(_, "File_Name")),
    rtr_ledger_stg_data_alias4 = Table.AddColumn(rtr_ledger_stg_data_alias3, "CHANNEL1", each Record.Field(_, "CHANNEL")),
    rtr_ledger_stg_data_alias5 = Table.AddColumn(rtr_ledger_stg_data_alias4, "REJECT_REASON1", each Record.Field(_, "REJECT_REASON")),
    rtr_ledger_stg_data = Table.SelectRows(rtr_ledger_stg_data_alias5, each Record.Field(_, "REJECT_REASON") = null)
in
    rtr_ledger_stg_data;

shared unprocessed_north_file_list = let
    rtr_ledger_north_rejected_alias1 = Table.AddColumn(exp_date_validation, "File_Name3", each Record.Field(_, "File_Name")),
    rtr_ledger_north_rejected_alias2 = Table.AddColumn(rtr_ledger_north_rejected_alias1, "REJECT_REASON3", each Record.Field(_, "REJECT_REASON")),
    rtr_ledger_north_rejected = Table.SelectRows(rtr_ledger_north_rejected_alias2, each (Record.Field(_, "REJECT_REASON") <> null) and (Record.Field(_, "CHANNEL") = "NORTH")),
    agg_north_rejects = Table.Distinct(Table.SelectColumns(rtr_ledger_north_rejected, {"File_Name3", "REJECT_REASON3"}))
in
    agg_north_rejects;

shared unprocessed_south_file_list = let
    rtr_ledger_south_rejected_alias1 = Table.AddColumn(exp_date_validation, "File_Name4", each Record.Field(_, "File_Name")),
    rtr_ledger_south_rejected_alias2 = Table.AddColumn(rtr_ledger_south_rejected_alias1, "REJECT_REASON4", each Record.Field(_, "REJECT_REASON")),
    rtr_ledger_south_rejected = Table.SelectRows(rtr_ledger_south_rejected_alias2, each (Record.Field(_, "REJECT_REASON") <> null) and (Record.Field(_, "CHANNEL") = "SOUTH")),
    agg_south_rejects = Table.Distinct(Table.SelectColumns(rtr_ledger_south_rejected, {"File_Name4", "REJECT_REASON4"}))
in
    agg_south_rejects;
