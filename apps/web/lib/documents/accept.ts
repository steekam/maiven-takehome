export const mediaType = "application/vnd.api+json";

function splitHeader(value: string, separator: string) {
  const parts: string[] = [];
  let start = 0;
  let quoted = false;
  for (let index = 0; index < value.length; index += 1) {
    if (value[index] === '"' && value[index - 1] !== "\\") quoted = !quoted;
    if (value[index] === separator && !quoted) {
      parts.push(value.slice(start, index).trim());
      start = index + 1;
    }
  }
  parts.push(value.slice(start).trim());
  return parts;
}

export function acceptsJsonApi(header: string | null) {
  if (!header?.trim()) return true;

  const matches: { specificity: number; acceptable: boolean; quality: number }[] = [];
  for (const range of splitHeader(header, ",")) {
    const [type, ...rawParameters] = splitHeader(range, ";");
    const mediaRange = type.toLowerCase();
    const specificity = mediaRange === mediaType ? 2
      : mediaRange === "application/*" ? 1
      : mediaRange === "*/*" ? 0
      : -1;
    if (specificity < 0) continue;

    let quality = 1;
    let acceptable = true;
    for (const parameter of rawParameters) {
      const separator = parameter.indexOf("=");
      if (separator < 0) continue;
      const name = parameter.slice(0, separator).trim().toLowerCase();
      const parameterValue = parameter.slice(separator + 1).trim().replace(/^"|"$/g, "");
      if (name === "q") {
        quality = Number(parameterValue);
        if (!Number.isFinite(quality) || quality < 0 || quality > 1) acceptable = false;
      } else if (specificity === 2 && (name === "ext" || name === "profile") && parameterValue) {
        acceptable = false;
      }
    }
    matches.push({ specificity, acceptable, quality });
  }

  const specificity = Math.max(...matches.map((match) => match.specificity), -1);
  return matches.some((match) => match.specificity === specificity && match.acceptable && match.quality > 0);
}
