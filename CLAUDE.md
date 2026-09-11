# TransitTicker

## Code comment style

Comments must describe the current code's behavior and rationale, not its
history. Avoid:

- "rather than" / "instead of" used to contrast the current approach against
  a rejected or prior alternative
- "previously", "originally", "no longer", "used to", "as before", "like it
  was", "would otherwise" - any phrasing that only makes sense to a reader
  who knows what the code used to do or what changed

Write every comment as if the current implementation is the only one that
has ever existed: state what it does and why, not what it changed from. When
a design trade-off is worth explaining (e.g. "no NAT Gateway - tasks sit in
public subnets, saving ~$32/month"), state the decision and its rationale
directly, without a "rather than X" comparison construction.
