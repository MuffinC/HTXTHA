// Renders model output as plain text (never HTML; CLAUDE.md section 7).
//
// Two kinds of token get a visual treatment so they cannot be mistaken for
// document text: the backend's PII masks ("[PHONE REDACTED]") become grey
// pills, and the mock provider's "[MOCK]" prefix becomes a small tag.
const TOKEN = /(\[(?:NRIC\/FIN|PHONE) REDACTED\]|\[MOCK\])/g;

export function ModelText({ text }: { text: string }) {
  const parts = text.split(TOKEN).filter((part) => part !== '');
  return (
    <>
      {parts.map((part, i) => {
        if (part === '[MOCK]') {
          return (
            <span key={i} className="mock-tag" title="Sample output from the mock provider">
              MOCK
            </span>
          );
        }
        if (part.endsWith('REDACTED]')) {
          return (
            <span key={i} className="redacted" title="Masked by the backend (MASK_PII)">
              {part.slice(1, -1).toLowerCase()}
            </span>
          );
        }
        return <span key={i}>{part.replace(/^\s+/, i > 0 ? ' ' : '')}</span>;
      })}
    </>
  );
}
