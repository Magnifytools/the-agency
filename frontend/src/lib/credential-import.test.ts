import { describe, expect, it } from "vitest"
import { parseCsv, readExport, selectedByDefault, toImportItem } from "./credential-import"

describe("parseCsv", () => {
  it("handles quotes, escaped quotes, commas and line breaks inside fields, CRLF and BOM", () => {
    const text = '\uFEFFa,b,c\r\n"x, y","say ""hi""","line 1\nline 2"\r\n\r\nlast,,\n'
    expect(parseCsv(text)).toEqual([["a", "b", "c"], ["x, y", 'say "hi"', "line 1\nline 2"], ["last", "", ""]])
  })
})

const ONEPASSWORD = [
  "Title,Url,Username,Password,OTPAuth,Favorite,Archived,Tags,Notes",
  'Google Ads,https://ads.google.com,ads@magnify.ing,pw-1,otpauth://totp/Google?secret=JBSWY3DPEHPK3PXP,false,false,,"Cuenta MCC"',
  "WordPress Fit,https://fit.example/wp-admin,magnify,pw-2,,false,false,,",
  "Nota segura,,,,,false,false,,Sólo texto",
  "Antigua,https://old.example,yo,pw-3,,false,true,,",
].join("\n")

describe("readExport", () => {
  it("reads a 1Password export with its 2FA links", () => {
    const { source, rows } = readExport(ONEPASSWORD)
    expect(source).toBe("1password")
    expect(rows[0]).toMatchObject({ line: 2, name: "Google Ads", url: "https://ads.google.com", username: "ads@magnify.ing",
      secret: "pw-1", totp: "otpauth://totp/Google?secret=JBSWY3DPEHPK3PXP", notes: "Cuenta MCC", problem: null })
    expect(rows[2].problem).toBe("Sin contraseña")
    expect(rows[3].archived).toBe(true)
    expect(rows.map(selectedByDefault)).toEqual([true, true, false, false])
  })

  it("reads Bitwarden (only logins) and Chrome exports", () => {
    const bitwarden = readExport([
      "folder,favorite,type,name,notes,fields,reprompt,login_uri,login_username,login_password,login_totp",
      ",,login,Semrush,,,0,https://semrush.com,equipo,pw,JBSWY3DPEHPK3PXP",
      ",,note,Wifi,clave,,0,,,,",
    ].join("\n"))
    expect(bitwarden.source).toBe("bitwarden")
    expect(bitwarden.rows[0]).toMatchObject({ name: "Semrush", username: "equipo", totp: "JBSWY3DPEHPK3PXP" })
    expect(bitwarden.rows[1].problem).toBe("No es un inicio de sesión")

    const chrome = readExport("name,url,username,password,note\nsemrush.com,https://semrush.com/login,equipo,pw,")
    expect(chrome.source).toBe("chrome")
    expect(chrome.rows[0]).toMatchObject({ name: "semrush.com", totp: null })
  })

  it("marks what already exists (same name and user) and repeated rows", () => {
    const { rows } = readExport(ONEPASSWORD + "\nGoogle Ads,https://ads.google.com,ADS@magnify.ing,otra,,false,false,,",
      [{ name: "wordpress fit", username: "Magnify" }])
    expect(rows[1].duplicate).toBe(true)
    expect(rows[4].duplicate).toBe(true)
    expect(rows[0].duplicate).toBe(false)
  })

  it("clips what does not fit instead of failing", () => {
    const long = "x".repeat(300)
    const { rows } = readExport(`Title,Url,Username,Password\n${long},https://${long}${long}.com,u,pw`)
    expect(rows[0].name).toHaveLength(200)
    expect(rows[0].name.endsWith("…")).toBe(true)
    expect(rows[0].url).toBeNull()
  })

  it("explains when the file is not a password export", () => {
    expect(() => readExport("fecha,importe\n2026-10-01,10")).toThrow(/faltan las columnas de nombre y contraseña/)
    expect(() => readExport("")).toThrow(/vacío/)
  })

  it("builds the item sent to the server", () => {
    const { rows } = readExport(ONEPASSWORD)
    expect(toImportItem(rows[1], 7)).toEqual({ name: "WordPress Fit", url: "https://fit.example/wp-admin", username: "magnify",
      secret: "pw-2", totp: null, notes: null, client_id: 7 })
  })
})
