import asyncio
import json
import random
import re
from dataclasses import dataclass
from typing import Any, Dict, List

from agents import Agent, Runner, gen_trace_id, trace
from agents.tracing import TracingProcessor, Span, Trace, set_trace_processors


class MemoryTraceProcessor(TracingProcessor):
    """Store traces and spans in memory for later export."""

    def __init__(self) -> None:
        self.traces: List[Trace] = []
        self.spans: List[Span[Any]] = []

    def on_trace_start(self, trace: Trace) -> None:
        self.traces.append(trace)

    def on_trace_end(self, trace: Trace) -> None:
        pass

    def on_span_start(self, span: Span[Any]) -> None:
        pass

    def on_span_end(self, span: Span[Any]) -> None:
        self.spans.append(span)

    def export(self) -> Dict[str, Any]:
        return {
            "traces": [t.export() for t in self.traces if t.export()],
            "spans": [s.export() for s in self.spans if s.export()],
        }


def _parse_nomination(text: str) -> str | None:
    match = re.search(r"Agent_\d+", text)
    return match.group(0) if match else None


@dataclass
class AgentInfo:
    agent: Agent
    score: int


class LeaderElectionGame:
    """Minimal leader election game using natural language communication."""

    def __init__(self, num_agents: int = 3) -> None:
        self.processor = MemoryTraceProcessor()
        set_trace_processors([self.processor])
        self.agents: List[AgentInfo] = []
        for i in range(num_agents):
            score = random.randint(1, 100)
            instructions = (
                f"You are Agent_{i+1}. Your private score is {score}.\n"
                "Nominate the agent with the highest known score. "
                "Say 'I nominate Agent_X'. If everyone agrees, finish with 'LEADER: Agent_X'."
            )
            agent = Agent(name=f"Agent_{i+1}", instructions=instructions)
            self.agents.append(AgentInfo(agent=agent, score=score))

    async def run(self, trace_file: str) -> Dict[str, Any]:
        conversation: List[str] = ["Begin leader election"]
        outputs: Dict[str, str] = {}
        trace_id = gen_trace_id()
        with trace("leader_election", trace_id=trace_id):
            for info in self.agents:
                result = await Runner.run(info.agent, conversation)
                outputs[info.agent.name] = result.final_output
                conversation = result.to_input_list()

        with open(trace_file, "w") as f:
            json.dump(self.processor.export(), f, indent=2)

        nominations = [_parse_nomination(o) for o in outputs.values() if _parse_nomination(o)]
        agreed = len(set(nominations)) == 1 if nominations else False
        return {"votes": outputs, "agreed": agreed}


async def main() -> None:
    game = LeaderElectionGame()
    result = await game.run("leader_election_trace.json")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
