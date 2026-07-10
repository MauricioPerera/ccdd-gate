// list_concepts — enumerate this origin's published knowledge concepts.
// The list is embedded at build time (content-addressed via tool_sha256).
var CONCEPTS = [{"id":"AGENTS.md","type":"Documentation","title":"Agentes de IA — empiecen acá","description":""},{"id":"BENCHMARKS.md","type":"Documentation","title":"Benchmarks","description":""},{"id":"README.md","type":"Documentation","title":"ccdd-gate","description":""}];
registerTool({
  name: "list_concepts",
  description: "List all knowledge concepts published by this origin (id, type, title, description).",
  inputSchema: { type: "object", properties: {} },
  handler: function () { return { concepts: CONCEPTS }; }
});
