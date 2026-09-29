# task=review

Adversarial second opinion on a decision or conclusion. Ask for objections and attack angles, not general thoughts.

## Prompt contents

Include:

- The question or decision, stated as it stands.
- Each supporting fact and its source — versions, counts, thresholds, error text, file names, symbols, command output, docs.
- Fixed constraints: deadlines, existing schemas, upstream decisions.
- Options already ruled out and why.
- The impact if the decision is wrong.

Mark unverified information as unverified — Codex treats stated facts as true.

## Prompt structure

Start with:

> You are an adversarial advisor. Answer only from the text below. Do not run shell commands, read files, or fetch information from the web. The prompt is your only source.

Then, matching the situation:

- Decision made → strongest objections and attack angles.
- Problem open → assumptions that may fail, what another framing would show.
- Conclusion settled → what must be true for it to be wrong, what evidence would show that.

Ask for the case against. Never provide a preferred fix before asking for objections — it biases the response.
