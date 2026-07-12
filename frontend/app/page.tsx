import { redirect } from "next/navigation";

/** Slice 8: 首页 = 信息流 */
export default function HomePage() {
  redirect("/feed");
}
