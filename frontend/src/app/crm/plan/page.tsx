import { redirect } from "next/navigation";

// Старый URL конструктора плана — редиректим на новый экран (табы «Собрать план» + «Согласование»).
export default function Page() {
  redirect("/crm/deals/planning");
}
