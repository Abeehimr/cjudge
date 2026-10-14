export type Language = "c11" | "cpp17";
export function languageName(language: Language = "c11") { return language === "cpp17" ? "C++17" : "C11"; }
export function sourceExtensions(languages: Language[] = ["c11"]) { return languages.map((language) => language === "cpp17" ? ".cpp" : ".c"); }
