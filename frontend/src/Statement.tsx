import Markdown from "react-markdown";

export default function Statement({ text }: { text: string }) {
  if (!text.trim()) return null;
  return <section aria-label="Task statement" className="statement rounded border bg-white p-4">
    <Markdown skipHtml disallowedElements={["img"]} urlTransform={(url) => {
      // Only explicit web links and local fragments. Never embed remote resources.
      return /^(https?:\/\/|#)/i.test(url) ? url : "";
    }}>{text}</Markdown>
  </section>;
}
