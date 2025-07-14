import argparse
import asyncio

from .leader_election import LeaderElectionGame


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run multi-agent tasks")
    parser.add_argument(
        "--task",
        choices=["leader_election"],
        default="leader_election",
        help="Task to execute",
    )
    parser.add_argument("--agents", type=int, default=3, help="Number of agents")
    parser.add_argument(
        "--trace-file", type=str, default="leader_election_trace.json", help="File to store trace JSON"
    )
    args = parser.parse_args()

    if args.task == "leader_election":
        game = LeaderElectionGame(num_agents=args.agents)
        result = await game.run(args.trace_file)
        print(result)


if __name__ == "__main__":
    asyncio.run(main())
