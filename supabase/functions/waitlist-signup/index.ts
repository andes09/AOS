import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'
import { Resend } from 'https://esm.sh/resend@3'
import { serve } from 'https://deno.land/std@0.201.0/http/server.ts'

// retunr email in env vars for security
serve(async (req) => {
Deno.serve(async (req) => {
  // Handle CORS preflight
  if (req.method === 'OPTIONS') {
    return new Response(null, { headers: corsHeaders })
  }

  try {
    const { email } = await req.json()

    if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      return new Response(
        JSON.stringify({ error: 'Invalid email address' }),
        { status: 400, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
      )
    }

    // Insert into Supabase using service role (bypasses RLS)
    const supabase = createClient(
      Deno.env.get('SUPABASE_URL')!,
      Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!
    )

    const { error: dbError } = await supabase
      .from('waitlist')
      .insert({ email: email.toLowerCase().trim() })

    // 23505 = unique_violation (already signed up) — still send success
    if (dbError && dbError.code !== '23505') {
      console.error('DB error:', dbError)
      return new Response(
        JSON.stringify({ error: 'Failed to save email' }),
        { status: 500, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
      )
    }
    const alreadySignedUp = dbError?.code === '23505'

    // Send thank you email (skip if already signed up to avoid spam)
    if (!alreadySignedUp) {
      const resend = new Resend(Deno.env.get('RESEND_API_KEY')!)
      await resend.emails.send({
        from: 'Agile OS <onbaording@devaos.com.app>', // change to your verified domain
        to: email,
        subject: "You're on the Agile OS waitlist",
        html: thankYouEmail(email),
      })
    }

    return new Response(
      JSON.stringify({ success: true }),
      { status: 200, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
    )
  } catch (err) {
    console.error('Unexpected error:', err)
    return new Response(
      JSON.stringify({ error: 'Internal server error' }),
      { status: 500, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
    )
  }
})

function thankYouEmail(email: string): string {
  return `
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>You're on the Agile OS waitlist</title>
</head>
<body style="margin:0;padding:0;background:#050505;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#050505;padding:48px 16px;">
    <tr>
      <td align="center">
        <table width="560" cellpadding="0" cellspacing="0" style="max-width:560px;width:100%;">

          <!-- Header -->
          <tr>
            <td style="padding-bottom:40px;border-bottom:1px solid rgba(240,235,224,0.08);">
              <p style="margin:0;font-size:22px;font-weight:400;letter-spacing:6px;color:#f0ebe0;text-transform:uppercase;">
                AOS
              </p>
            </td>
          </tr>

          <!-- Body -->
          <tr>
            <td style="padding:48px 0 32px;">
              <h1 style="margin:0 0 24px;font-size:36px;font-weight:300;color:#f0ebe0;line-height:1.2;">
                You're on the list.
              </h1>
              <p style="margin:0 0 16px;font-size:15px;color:#7a7470;line-height:1.8;">
                Thank you for signing up for the Agile OS waitlist. We're building the planning and intelligence platform that helps engineering teams stop repeating the same sprint failures.
              </p>
              <p style="margin:0 0 32px;font-size:15px;color:#7a7470;line-height:1.8;">
                We're onboarding beta teams now. When your spot is ready, you'll be the first to know.
              </p>

              <!-- What to expect -->
              <table width="100%" cellpadding="0" cellspacing="0" style="background:#0c0c0c;border:1px solid rgba(240,235,224,0.06);margin-bottom:40px;">
                <tr>
                  <td style="padding:28px 32px;">
                    <p style="margin:0 0 20px;font-size:10px;font-weight:700;letter-spacing:3px;text-transform:uppercase;color:#c4a35a;">
                      What's coming
                    </p>
                    <table width="100%" cellpadding="0" cellspacing="0">
                      ${[
                        ['Scope Cop', 'Ticket quality enforced before planning begins'],
                        ['Sprint Brain', 'Plans built on your team\'s actual delivery history'],
                        ['Dependency Radar', 'Reliability scores for every external dependency'],
                        ['Velocity Mirror', 'Sprint failures caught before they\'re inevitable'],
                        ['Retrospective AI', 'Automated learning that compounds every sprint'],
                      ].map(([name, desc]) => `
                      <tr>
                        <td style="padding:10px 0;border-bottom:1px solid rgba(240,235,224,0.05);">
                          <p style="margin:0 0 3px;font-size:13px;font-weight:600;color:#f0ebe0;">${name}</p>
                          <p style="margin:0;font-size:12px;color:#7a7470;">${desc}</p>
                        </td>
                      </tr>`).join('')}
                    </table>
                  </td>
                </tr>
              </table>

              <p style="margin:0;font-size:14px;color:#3d3a36;line-height:1.8;">
                Works on top of Jira, Linear, and GitHub Projects. No migration required.
              </p>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="padding-top:32px;border-top:1px solid rgba(240,235,224,0.06);">
              <p style="margin:0 0 8px;font-size:11px;color:#3d3a36;letter-spacing:1px;">
                AGILE OS — The Operating System for Engineering Teams
              </p>
              <p style="margin:0;font-size:11px;color:#3d3a36;">
                You're receiving this because you signed up at agileos.app.
                <br/>Reply to unsubscribe at any time.
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>
  `.trim()
}
