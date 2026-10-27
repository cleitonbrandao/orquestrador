import { Plugin } from "@opencode/plugin"

// O Ollama só desliga o thinking com reasoning_effort: "none" no corpo.
// O OpenCode 2.1.3 não envia body de provider/modelo, então injetamos via hook.
const noThink = (event: any) => {
  event.options.reasoningEffort = "none"
  event.options.reasoning_effort = "none"
}

export default Plugin.define({
  id: "ollama.nothink",
  async setup(ctx) {
    for (const hook of ["context", "title", "compaction", "generate"] as const) {
      await ctx.session.hook(hook, noThink, { providerID: "ollama" })
    }
  },
})
