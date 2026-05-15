import type { NextAuthOptions } from 'next-auth'
import CredentialsProvider from 'next-auth/providers/credentials'

export const authOptions: NextAuthOptions = {
  secret: process.env.NEXTAUTH_SECRET,
  session: { strategy: 'jwt', maxAge: 30 * 24 * 60 * 60 },
  pages: { signIn: '/login' },
  providers: [
    CredentialsProvider({
      name: 'Password',
      credentials: {
        password: { label: 'Password', type: 'password' },
      },
      async authorize(credentials) {
        const password = process.env.REVIEW_UI_PASSWORD
        if (!password) {
          throw new Error('REVIEW_UI_PASSWORD is not set')
        }
        if (credentials?.password === password) {
          return { id: '1', name: 'Admin', email: 'admin@local' }
        }
        return null
      },
    }),
  ],
  callbacks: {
    jwt({ token }) {
      return token
    },
    session({ session }) {
      return session
    },
  },
}
