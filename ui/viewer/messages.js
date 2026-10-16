// The header every message carries, the same fields as common/codec.py:
// { msg_id, source_id, t_sent, seq, schema_version }, plus a top-level `type` on the message itself.
(function (global) {
  const SCHEMA_VERSION = 1;
  const HEADER_FIELDS = ['msg_id', 'source_id', 't_sent', 'seq', 'schema_version'];

  // seq counts per source (from 1) so msg_id is unique; t_sent is the sender's own clock
  function makeHeader(seqs, source, tSent) {
    const seq = (seqs[source] = (seqs[source] || 0) + 1);
    return { msg_id: source + '-' + seq, source_id: source, t_sent: tSent, seq, schema_version: SCHEMA_VERSION };
  }

  const api = { makeHeader, HEADER_FIELDS, SCHEMA_VERSION };
  global.Messages = api;
  if (typeof module !== 'undefined') module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
