# Usability Sessions

Phase 14's last task (plan, task 49) is to watch at least three people who
have never used a prediction market try the app, fix what they stumble on,
and report it. It needs the deployed host and real people, so it runs after
the cloud deploy (flag F16); this page is the protocol, fixed in advance so
the sessions measure the app rather than the facilitator.

## Who

At least three adults who have never traded on a prediction market and do
not work in software or finance; one of them uses a screen reader or
keyboard only, which is also the real screen-reader pass of task 47. No
one who has seen the app before. Each is told what the session is for, that
the app is being tested and not them, that they may stop at any time, and
what is kept (below); they agree before it starts.

## How

One person at a time, 45 minutes, on their own computer or phone, over a
call with screen sharing. They think aloud; the facilitator does not help,
and answers a question with "what would you try?". The facilitator notes
the time each task starts and ends, where they hesitate, and every word
they misread or ask about, verbatim. No recording unless they agree to it;
notes name no one.

## Tasks

Each is read out as written, one at a time. A task is **completed** when
the success condition holds without help, **assisted** if it holds after
one hint, **failed** otherwise.

| # | Task as read | Success |
| :--- | :--- | :--- |
| 1 | "Sign in with your email." | on Home, having ticked the age and terms box |
| 2 | "What is this site for, in your own words?" | mentions testing strategies and play money |
| 3 | "Find a market you find interesting and tell me what the site thinks will happen." | states a market's chance in words |
| 4 | "How much would it cost to buy one 'Yes' share there?" | the price and the fee, roughly |
| 5 | "How is the sample strategy doing?" | the balance and whether it beats doing nothing |
| 6 | "Would that strategy have made money in the past? Find out." | a backtest run from the page and its result read |
| 7 | "What has all this cost you?" | the model spending line |
| 8 | "Change the site so it shows you more detail." | Detailed switched on |
| 9 | "You want to leave and take your data with you. Do that, but stop before anything is deleted." | the export downloaded, the deletion form found |
| 10 | (Phase 15 onward) "Describe a strategy you'd like to try, and watch it trade." | a strategy of their own confirmed and in paper |

## Measures

- Completion per task: completed, assisted, failed.
- **Time to first strategy watched**: from the start of task 1 to the
  moment they read the sample strategy's balance in task 5.
- **Words that confused**: every term they asked about or misread, with
  the screen, verbatim.
- After the session: "What was the most confusing moment?" and "Would you
  use this again, and for what?", written down as said.

## After

Each confusing word gets a change to its catalogue entry
(`vp/ui/static/app/locales/en.json`) or its glossary definition; each
failed task gets a fix or a stated reason not to. The Phase 14 report adds
a section with the three tables (completion, times, words) and the list of
fixes, and the sessions are repeated with new people if more than one task
failed for two or more participants.
