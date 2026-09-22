import { AxiosError, AxiosHeaders } from "axios"
import { expect, it } from "vitest"
import { getErrorMessage } from "./utils"

it("shows the server message for structured digest rejections", () => {
  const error = new AxiosError("Request failed")
  error.response = {
    data: { detail: { code: "policy_missing", message: "Configura los resúmenes del cliente." } },
    status: 409,
    statusText: "Conflict",
    headers: {},
    config: { headers: new AxiosHeaders() },
  }
  expect(getErrorMessage(error)).toBe("Configura los resúmenes del cliente.")
})
