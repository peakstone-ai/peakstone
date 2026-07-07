import type { MetadataRoute } from "next";

// The crawlable surface: the stable top-level pages (detail pages are discovered by links).
export default function sitemap(): MetadataRoute.Sitemap {
  const base = "https://peakstone.ai";
  return ["", "/leaderboard", "/challenges", "/evolution", "/proposals", "/submit"].map((p) => ({
    url: `${base}${p}`,
    changeFrequency: p === "" || p === "/submit" ? "weekly" : "daily",
  }));
}
