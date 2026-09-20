---
id: information-needs
description: Create and close candidate-specific needs using the existing InformationNeed model.
phases: planning, recovery
trigger-tags: information-needs, candidate, policy-need, tool-need
priority: 85
---

# Candidate-Specific Information Needs

Represent a gap with existing `InformationNeed.entity` as the candidate identity and `aspect` as the missing criterion. Set `source`, `priority`, `critical`, and `status` normally.

- A candidate A Fact cannot resolve candidate B's Need.
- A hard-constraint Need is critical until authoritative evidence establishes compliance or violation.
- Optional ranking detail may remain non-critical.
- USER supplies preference/intent; TOOL supplies live state; POLICY supplies policy meaning.
- Stop when all surviving candidates have critical coverage and enough optional evidence for the requested comparison.

