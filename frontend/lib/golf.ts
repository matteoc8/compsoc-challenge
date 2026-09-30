// Must match backend/app/judge/golf.py exactly: \r\n → \n, strip ASCII whitespace at the
// end of the file, count Unicode code points.
export function golfChars(code: string): number {
  const s = code.replace(/\r\n/g, "\n").replace(/[ \t\n\r\f\v]+$/, "");
  return Array.from(s).length;
}
