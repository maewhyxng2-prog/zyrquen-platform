import { cookies } from "next/headers";
import { NextResponse } from "next/server";

export async function GET() {
  const cookieStore = await cookies();
  return NextResponse.json(
    {
      authenticated: Boolean(cookieStore.get("zyrquen_access")?.value),
      email: cookieStore.get("zyrquen_email")?.value ?? null,
    },
    { headers: { "Cache-Control": "no-store" } },
  );
}
