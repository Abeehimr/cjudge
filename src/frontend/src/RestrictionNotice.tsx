export type Restriction = { identifier: string; line: number } | null;

export default function RestrictionNotice({ restriction }: { restriction?: Restriction }) {
  return restriction && <p className="text-red-800">Banned identifier <code>{restriction.identifier}</code> at line {restriction.line}.</p>;
}
