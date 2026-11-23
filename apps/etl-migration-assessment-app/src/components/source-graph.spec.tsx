import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SourceGraph } from "@/components/source-graph";

const nodes = [
  {
    NodeId: "1",
    NodeName: "InputData",
    NodeLabel: "Orders",
    Plugin: "AlteryxBasePluginsGui.DbFileInput",
    SupportCategory: "dataflow",
    Disabled: false,
    X: 100,
    Y: 80,
  },
  {
    NodeId: "2",
    NodeName: "Filter",
    NodeLabel: "Current orders",
    Plugin: "AlteryxBasePluginsGui.Filter",
    SupportCategory: "dataflow",
    Disabled: false,
    X: 300,
    Y: 80,
  },
  {
    NodeId: "3",
    NodeName: "Python",
    NodeLabel: "Custom scoring",
    Plugin: "JupyterTool",
    SupportCategory: "manual",
    Disabled: false,
    X: 500,
    Y: 140,
  },
];

const connections = [
  {
    SourceNodeId: "1",
    TargetNodeId: "2",
    SourceAnchor: "Output",
    TargetAnchor: "Input",
  },
  {
    SourceNodeId: "2",
    TargetNodeId: "3",
    SourceAnchor: "True",
    TargetAnchor: "Input",
  },
];

describe("SourceGraph", () => {
  it("renders connected source coordinates instead of a flattened card strip", () => {
    const { container } = render(
      <SourceGraph nodes={nodes} connections={connections} />,
    );

    expect(screen.getByRole("img", { name: "Source workflow graph" }))
      .toBeInTheDocument();
    expect(screen.getByText("3 tools · 2 connections · source coordinates"))
      .toBeInTheDocument();
    expect(container.querySelectorAll(".source-graph-edge")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Tool 3: Custom scoring" }))
      .toHaveClass("support-manual");
  });

  it("supports search, selection, zoom, and a complete text alternative", () => {
    render(<SourceGraph nodes={nodes} connections={connections} />);

    fireEvent.change(screen.getByRole("textbox", { name: "Find source workflow tool" }), {
      target: { value: "scoring" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Find / next" }));
    expect(screen.getByText("Custom scoring", { selector: "strong" }))
      .toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Zoom in source workflow graph" }));
    expect(screen.getByText("95%")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Text alternative: source tool register"));
    expect(screen.getByText("Tool 1: Orders (Dataflow)")).toBeInTheDocument();
    expect(screen.getByText("Tool 3: Custom scoring (Manual redesign)"))
      .toBeInTheDocument();
  });

  it("derives a layered layout when source coordinates are unavailable", () => {
    render(
      <SourceGraph
        nodes={nodes.map((node) => ({ ...node, X: null, Y: null }))}
        connections={connections}
      />,
    );

    expect(screen.getByText("3 tools · 2 connections · derived layout"))
      .toBeInTheDocument();
  });

  it("uses compact web-app geometry and omits unbounded containers", () => {
    const records = [
      ...nodes.map((node, index) => ({ ...node, X: 48 + index * 120 })),
      {
        NodeId: "100",
        NodeName: "ToolContainer",
        NodeLabel: "Preparation",
        Plugin: "ToolContainer",
        SupportCategory: "neutral",
        Disabled: false,
        X: 300,
        Y: 80,
      },
    ];
    const { container } = render(
      <SourceGraph nodes={records} connections={connections} />,
    );

    expect(screen.queryByRole("button", { name: "Tool 100: Preparation" }))
      .not.toBeInTheDocument();
    expect(screen.getByText(/1 container listed in the tool register/))
      .toBeInTheDocument();
    const rectangles = [...container.querySelectorAll(".source-graph-node rect")];
    expect(rectangles).toHaveLength(3);
    expect(rectangles[0]).toHaveAttribute("width", "72");
    expect(rectangles[0]).toHaveAttribute("height", "42");
    const firstX = Number(rectangles[0].getAttribute("x"));
    const secondX = Number(rectangles[1].getAttribute("x"));
    expect(secondX - firstX).toBeGreaterThanOrEqual(72);
  });
});
