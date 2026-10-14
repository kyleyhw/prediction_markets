// Where Gemini's free tier may serve people, and where Google allows only
// its paid tier; vp/llm/providers.py is the source, and tests/test_demo.py
// fails if the two differ (docs/models.md on the reasons).
export const FREE_TIER = new Set([
  'AD', 'AE', 'AG', 'AI', 'AL', 'AM', 'AO', 'AQ', 'AR', 'AS', 'AU', 'AW', 'AZ', 'BA', 'BB', 'BD',
  'BF', 'BH', 'BI', 'BJ', 'BL', 'BM', 'BN', 'BO', 'BQ', 'BR', 'BS', 'BT', 'BW', 'BZ', 'CA', 'CC',
  'CD', 'CF', 'CG', 'CI', 'CK', 'CL', 'CM', 'CO', 'CR', 'CV', 'CW', 'CX', 'DJ', 'DM', 'DO', 'DZ',
  'EC', 'EG', 'EH', 'ER', 'ET', 'FJ', 'FK', 'FM', 'FO', 'GA', 'GD', 'GE', 'GH', 'GL', 'GM', 'GN',
  'GQ', 'GS', 'GT', 'GU', 'GW', 'GY', 'HM', 'HN', 'HT', 'ID', 'IL', 'IN', 'IO', 'IQ', 'JM', 'JO',
  'JP', 'KE', 'KG', 'KH', 'KI', 'KM', 'KN', 'KR', 'KW', 'KY', 'KZ', 'LA', 'LB', 'LC', 'LK', 'LR',
  'LS', 'LY', 'MA', 'MC', 'MD', 'ME', 'MG', 'MH', 'MK', 'ML', 'MN', 'MP', 'MR', 'MS', 'MU', 'MV',
  'MW', 'MX', 'MY', 'MZ', 'NA', 'NC', 'NE', 'NF', 'NG', 'NI', 'NP', 'NR', 'NU', 'NZ', 'OM', 'PA',
  'PE', 'PG', 'PH', 'PK', 'PM', 'PN', 'PR', 'PS', 'PW', 'PY', 'QA', 'RS', 'RW', 'SA', 'SB', 'SC',
  'SD', 'SG', 'SH', 'SL', 'SM', 'SN', 'SO', 'SR', 'SS', 'ST', 'SV', 'SZ', 'TC', 'TD', 'TG', 'TH',
  'TJ', 'TK', 'TL', 'TM', 'TN', 'TO', 'TR', 'TT', 'TV', 'TW', 'TZ', 'UA', 'UG', 'UM', 'US', 'UY',
  'UZ', 'VA', 'VC', 'VE', 'VG', 'VI', 'VN', 'VU', 'WF', 'WS', 'XK', 'YE', 'ZA', 'ZM', 'ZW',
]);
export const PAID_ONLY = new Set([
  'AT', 'AX', 'BE', 'BG', 'CH', 'CY', 'CZ', 'DE', 'DK', 'EE', 'ES', 'FI', 'FR', 'GB', 'GF', 'GG',
  'GI', 'GP', 'GR', 'HR', 'HU', 'IE', 'IM', 'IS', 'IT', 'JE', 'LI', 'LT', 'LU', 'LV', 'MF', 'MQ',
  'MT', 'NL', 'NO', 'PL', 'PT', 'RE', 'RO', 'SE', 'SI', 'SK', 'YT',
]);
