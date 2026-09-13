/** The only path for data-originating strings into rendered document text. */
export function appendText(parent: Node, value: unknown): Text {
  const node = document.createTextNode(value === null || value === undefined ? "—" : String(value));
  parent.appendChild(node);
  return node;
}

export function element<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  options: { className?: string; text?: unknown } = {},
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (options.className) node.className = options.className;
  if (Object.hasOwn(options, "text")) appendText(node, options.text);
  return node;
}

export function localLink(label: unknown, fragment: string): HTMLAnchorElement {
  if (!fragment.startsWith("#/")) throw new Error("navigation must remain in this document");
  const link = element("a");
  link.href = fragment;
  appendText(link, label);
  return link;
}

export function section(title: string): HTMLElement {
  const node = element("section", { className: "panel" });
  node.append(element("h2", { text: title }));
  return node;
}

export function addDefinition(list: HTMLDListElement, label: string, value: unknown): void {
  list.append(element("dt", { text: label }), element("dd", { text: value }));
}

export function renderJson(value: unknown): HTMLElement {
  const pre = element("pre", { className: "code" });
  appendText(pre, JSON.stringify(value, null, 2));
  return pre;
}
