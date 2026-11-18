section Section1;

shared SourceBindings = error "Configure source bindings before refresh";

shared src_businessdate = let
    src_businessdate = Record.Field(SourceBindings, "1")
in
    src_businessdate;

shared src_broadridge_current = let
    src_broadridge_current = Record.Field(SourceBindings, "2")
in
    src_broadridge_current;

shared src_gr_current = let
    src_gr_current = Record.Field(SourceBindings, "3")
in
    src_gr_current;

shared src_gr_previous = let
    src_gr_previous = Record.Field(SourceBindings, "4")
in
    src_gr_previous;

shared src_lopr_details = let
    src_lopr_details = Record.Field(SourceBindings, "5")
in
    src_lopr_details;

shared src_ocend_current = let
    src_ocend_current = Record.Field(SourceBindings, "6")
in
    src_ocend_current;

shared src_ocend_previous = let
    src_ocend_previous = Record.Field(SourceBindings, "7")
in
    src_ocend_previous;

shared src_sharepointfiles = let
    src_sharepointfiles = Record.Field(SourceBindings, "8")
in
    src_sharepointfiles;

shared src_broadridge_previous = let
    src_broadridge_previous = Record.Field(SourceBindings, "9")
in
    src_broadridge_previous;

shared qgr_current_calculated = let
    qgr_current_calculated = Table.AddColumn(src_gr_current, "CalculatedAmount", each Number.From(Record.Field(_, "Amount")))
in
    qgr_current_calculated;

shared qgr_previous_calculated = let
    qgr_previous_calculated = Table.AddColumn(src_gr_previous, "CalculatedAmount", each Number.From(Record.Field(_, "Amount")))
in
    qgr_previous_calculated;

shared qgr_ocend_current = src_ocend_current;

shared qgr_ocend_previous = src_ocend_previous;

shared qgr_ocend_combined = let
    qgr_ocend_combined = Table.Combine({qgr_ocend_current, qgr_ocend_previous})
in
    qgr_ocend_combined;

shared qlopr_entitylookup = src_lopr_details;

shared qgr_ocend_enriched = let
    qgr_ocend_enriched_Joined = Table.NestedJoin(qgr_ocend_combined, {"RecordKey"}, qlopr_entitylookup, {"RecordKey"}, "__right", JoinKind.Inner),
    qgr_ocend_enriched_RightColumns = List.RemoveItems(Table.ColumnNames(qlopr_entitylookup), {"RecordKey"}),
    qgr_ocend_enriched_OutputColumns = List.Transform(qgr_ocend_enriched_RightColumns, each if List.Contains(Table.ColumnNames(qgr_ocend_combined), _) then _ & "_Right" else _),
    qgr_ocend_enriched = Table.ExpandTableColumn(qgr_ocend_enriched_Joined, "__right", qgr_ocend_enriched_RightColumns, qgr_ocend_enriched_OutputColumns)
in
    qgr_ocend_enriched;

shared qlopr_accountlookup = src_lopr_details;

shared qgr_ocend_calculated = let
    qgr_ocend_calculated_Joined = Table.NestedJoin(qgr_ocend_enriched, {"RecordKey"}, qlopr_accountlookup, {"RecordKey"}, "__right", JoinKind.Inner),
    qgr_ocend_calculated_RightColumns = List.RemoveItems(Table.ColumnNames(qlopr_accountlookup), {"RecordKey"}),
    qgr_ocend_calculated_OutputColumns = List.Transform(qgr_ocend_calculated_RightColumns, each if List.Contains(Table.ColumnNames(qgr_ocend_enriched), _) then _ & "_Right" else _),
    qgr_ocend_calculated = Table.ExpandTableColumn(qgr_ocend_calculated_Joined, "__right", qgr_ocend_calculated_RightColumns, qgr_ocend_calculated_OutputColumns)
in
    qgr_ocend_calculated;

shared qbroadridge_current_calculated = let
    qbroadridge_current_calculated = Table.AddColumn(src_broadridge_current, "CalculatedAmount", each Number.From(Record.Field(_, "Amount")))
in
    qbroadridge_current_calculated;

shared qbroadridge_current_result = let
    qbroadridge_current_matched_Joined = Table.NestedJoin(qbroadridge_current_calculated, {"RecordKey"}, qgr_current_calculated, {"RecordKey"}, "__right", JoinKind.Inner),
    qbroadridge_current_matched_RightColumns = List.RemoveItems(Table.ColumnNames(qgr_current_calculated), {"RecordKey"}),
    qbroadridge_current_matched_OutputColumns = List.Transform(qbroadridge_current_matched_RightColumns, each if List.Contains(Table.ColumnNames(qbroadridge_current_calculated), _) then _ & "_Right" else _),
    qbroadridge_current_matched = Table.ExpandTableColumn(qbroadridge_current_matched_Joined, "__right", qbroadridge_current_matched_RightColumns, qbroadridge_current_matched_OutputColumns)
in
    qbroadridge_current_matched;

shared qbroadridge_previous_calculated = let
    qbroadridge_previous_calculated = Table.AddColumn(src_broadridge_previous, "CalculatedAmount", each Number.From(Record.Field(_, "Amount")))
in
    qbroadridge_previous_calculated;

shared qbroadridge_previous_result = let
    qbroadridge_previous_matched_Joined = Table.NestedJoin(qbroadridge_previous_calculated, {"RecordKey"}, qgr_previous_calculated, {"RecordKey"}, "__right", JoinKind.Inner),
    qbroadridge_previous_matched_RightColumns = List.RemoveItems(Table.ColumnNames(qgr_previous_calculated), {"RecordKey"}),
    qbroadridge_previous_matched_OutputColumns = List.Transform(qbroadridge_previous_matched_RightColumns, each if List.Contains(Table.ColumnNames(qbroadridge_previous_calculated), _) then _ & "_Right" else _),
    qbroadridge_previous_matched = Table.ExpandTableColumn(qbroadridge_previous_matched_Joined, "__right", qbroadridge_previous_matched_RightColumns, qbroadridge_previous_matched_OutputColumns)
in
    qbroadridge_previous_matched;

shared qbroadridge_combined = let
    qbroadridge_combined = Table.Combine({qbroadridge_current_result, qbroadridge_previous_result})
in
    qbroadridge_combined;

shared out_broadridge = qbroadridge_combined;

shared out_gr_ocend = qgr_ocend_calculated;

shared file_broadridge_export = out_broadridge;

shared load_broadridge = out_broadridge;

shared file_gr_ocend_export = out_gr_ocend;

shared load_gr_ocend = out_gr_ocend;
