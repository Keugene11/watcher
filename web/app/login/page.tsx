import { redirect } from "next/navigation";
import { loginRequired } from "@/lib/auth";
import LoginForm from "./form";

export const dynamic = "force-dynamic";

export default function Login() {
  if (!loginRequired()) redirect("/");
  return <LoginForm />;
}
