section Section1;

shared SourceBindings = error "Configure source bindings before refresh";

shared src_businessdate = let
    src_businessdate = Record.Field(SourceBindings, "1")
in
    src_businessdate;

shared src_settlement_current = let
    src_settlement_current = Record.Field(SourceBindings, "2")
in
    src_settlement_current;

shared src_alpha_current = let
    src_alpha_current = Record.Field(SourceBindings, "3")
in
    src_alpha_current;

shared src_alpha_previous = let
    src_alpha_previous = Record.Field(SourceBindings, "4")
in
    src_alpha_previous;

shared src_ref_details = let
    src_ref_details = Record.Field(SourceBindings, "5")
in
    src_ref_details;

shared src_beta_current = let
    src_beta_current = Record.Field(SourceBindings, "6")
in
    src_beta_current;

shared src_beta_previous = let
    src_beta_previous = Record.Field(SourceBindings, "7")
in
    src_beta_previous;

shared src_manifestfiles = let
    src_manifestfiles = Record.Field(SourceBindings, "8")
in
    src_manifestfiles;

shared src_settlement_previous = let
    src_settlement_previous = Record.Field(SourceBindings, "9")
in
    src_settlement_previous;

shared qalpha_current_calculated = let
    qalpha_current_calculated = Table.AddColumn(src_alpha_current, "CalculatedAmount", each Number.From(Record.Field(_, "Amount")))
in
    qalpha_current_calculated;

shared qalpha_previous_calculated = let
    qalpha_previous_calculated = Table.AddColumn(src_alpha_previous, "CalculatedAmount", each Number.From(Record.Field(_, "Amount")))
in
    qalpha_previous_calculated;

shared qalpha_beta_current = src_beta_current;

shared qalpha_beta_previous = src_beta_previous;

shared qalpha_beta_combined = let
    qalpha_beta_combined = Table.Combine({qalpha_beta_current, qalpha_beta_previous})
in
    qalpha_beta_combined;

shared qref_entitylookup = src_ref_details;

shared qalpha_beta_enriched = let
    qalpha_beta_enriched_Joined = Table.NestedJoin(qalpha_beta_combined, {"RecordKey"}, qref_entitylookup, {"RecordKey"}, "__right", JoinKind.Inner),
    qalpha_beta_enriched_RightColumns = List.RemoveItems(Table.ColumnNames(qref_entitylookup), {"RecordKey"}),
    qalpha_beta_enriched_OutputColumns = List.Transform(qalpha_beta_enriched_RightColumns, each if List.Contains(Table.ColumnNames(qalpha_beta_combined), _) then _ & "_Right" else _),
    qalpha_beta_enriched = Table.ExpandTableColumn(qalpha_beta_enriched_Joined, "__right", qalpha_beta_enriched_RightColumns, qalpha_beta_enriched_OutputColumns)
in
    qalpha_beta_enriched;

shared qref_accountlookup = src_ref_details;

shared qalpha_beta_calculated = let
    qalpha_beta_calculated_Joined = Table.NestedJoin(qalpha_beta_enriched, {"RecordKey"}, qref_accountlookup, {"RecordKey"}, "__right", JoinKind.Inner),
    qalpha_beta_calculated_RightColumns = List.RemoveItems(Table.ColumnNames(qref_accountlookup), {"RecordKey"}),
    qalpha_beta_calculated_OutputColumns = List.Transform(qalpha_beta_calculated_RightColumns, each if List.Contains(Table.ColumnNames(qalpha_beta_enriched), _) then _ & "_Right" else _),
    qalpha_beta_calculated = Table.ExpandTableColumn(qalpha_beta_calculated_Joined, "__right", qalpha_beta_calculated_RightColumns, qalpha_beta_calculated_OutputColumns)
in
    qalpha_beta_calculated;

shared qsettlement_current_calculated = let
    qsettlement_current_calculated = Table.AddColumn(src_settlement_current, "CalculatedAmount", each Number.From(Record.Field(_, "Amount")))
in
    qsettlement_current_calculated;

shared qsettlement_current_result = let
    qsettlement_current_matched_Joined = Table.NestedJoin(qsettlement_current_calculated, {"RecordKey"}, qalpha_current_calculated, {"RecordKey"}, "__right", JoinKind.Inner),
    qsettlement_current_matched_RightColumns = List.RemoveItems(Table.ColumnNames(qalpha_current_calculated), {"RecordKey"}),
    qsettlement_current_matched_OutputColumns = List.Transform(qsettlement_current_matched_RightColumns, each if List.Contains(Table.ColumnNames(qsettlement_current_calculated), _) then _ & "_Right" else _),
    qsettlement_current_matched = Table.ExpandTableColumn(qsettlement_current_matched_Joined, "__right", qsettlement_current_matched_RightColumns, qsettlement_current_matched_OutputColumns)
in
    qsettlement_current_matched;

shared qsettlement_previous_calculated = let
    qsettlement_previous_calculated = Table.AddColumn(src_settlement_previous, "CalculatedAmount", each Number.From(Record.Field(_, "Amount")))
in
    qsettlement_previous_calculated;

shared qsettlement_previous_result = let
    qsettlement_previous_matched_Joined = Table.NestedJoin(qsettlement_previous_calculated, {"RecordKey"}, qalpha_previous_calculated, {"RecordKey"}, "__right", JoinKind.Inner),
    qsettlement_previous_matched_RightColumns = List.RemoveItems(Table.ColumnNames(qalpha_previous_calculated), {"RecordKey"}),
    qsettlement_previous_matched_OutputColumns = List.Transform(qsettlement_previous_matched_RightColumns, each if List.Contains(Table.ColumnNames(qsettlement_previous_calculated), _) then _ & "_Right" else _),
    qsettlement_previous_matched = Table.ExpandTableColumn(qsettlement_previous_matched_Joined, "__right", qsettlement_previous_matched_RightColumns, qsettlement_previous_matched_OutputColumns)
in
    qsettlement_previous_matched;

shared qsettlement_combined = let
    qsettlement_combined = Table.Combine({qsettlement_current_result, qsettlement_previous_result})
in
    qsettlement_combined;

shared out_settlement = qsettlement_combined;

shared out_alpha_beta = qalpha_beta_calculated;

shared file_settlement_export = out_settlement;

shared load_settlement = out_settlement;

shared file_alpha_beta_export = out_alpha_beta;

shared load_alpha_beta = out_alpha_beta;
