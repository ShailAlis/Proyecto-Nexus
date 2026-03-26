// Pruebas unitarias para el servicio de autenticación
import { AuthService } from '../src/auth/AuthService';

describe('AuthService', () => {
  let authService: AuthService;

  beforeEach(() => {
    authService = new AuthService();
  });

  it('should authenticate a user with valid credentials', () => {
    expect(authService.login('user', 'password')).toBe(true);
  });
});
