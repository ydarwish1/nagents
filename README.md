# nagents

**Do more AI agents beat one? Measured.**

A common trick is to ask several AI agents the same question and go with the
most common answer. nagents tests whether that works. It gives the same
problems to groups of 1, 3, 5 and up to 9 agents, checks every answer, and
shows how much each extra agent helps and what it costs. Every agent's full
reply is saved, so every number traces back to what an agent said.

## What we found

We asked Claude Haiku and Claude Sonnet to multiply big numbers in their
heads, with no tools.

![Accuracy by group size. Haiku on 7-digit problems climbs from 58% with one agent to 98% with nine. Haiku on 8-digit problems climbs from 38% to 91%. Sonnet on 20-digit problems goes from 95% to 100% with five.](docs/img/study-voting.svg)

**1. Voting works.** One Haiku got 7-digit problems right 58% of the time.
A vote of 9 Haikus got 98%. It works because the agents almost never make
the *same* mistake, so the right answer wins even when most agents are wrong.

**2. A smarter model beats a crowd.** Haiku falls apart past 8 digits.
Sonnet was still right 95% of the time on 20-digit problems, and 5 Sonnets
voting got every one right.

![One agent alone. Haiku drops from 88% at 5 digits to 6% at 9 digits. Sonnet stays between 95% and 100% all the way to 20 digits.](docs/img/study-models.svg)

**3. Talking it over beats voting.** When 3 agents could see each other's
answers and fix their own, they got all 40 problems right. A plain vote got
78%. It used about 2.6 times as many tokens.

![Debate vs. voting on 7-digit problems: with 3 or 5 agents, debate got 100% and voting 78 to 83%.](docs/img/study-debate.svg)

**4. Use an odd number of agents.** Two agents are no better than one,
because when they disagree it's a coin toss.

## Try it (free, 10 seconds)

```bash
python3 -m nagents run --mock --suite chain --depth 8 --trials 40 --sizes 1,3,5,9 --out runs/demo
open runs/demo/report.html
```

This uses a fake built-in model, so no API key is needed. To run real
models (Claude subagents, the Claude API, or OpenAI's GPT models), see
**[the guide](docs/GUIDE.md)**. Every run behind these charts is in `study/`,
and [SPEC.md](SPEC.md) has the full numbers and caveats.

*Limits: one kind of task (arithmetic), 40 problems per point, and
Haiku and Sonnet only so far.*
