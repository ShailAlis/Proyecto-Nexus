// Controlador para manejar las solicitudes de autenticación
import { AuthService } from './AuthService';

export class AuthController {
  private authService: AuthService;

  constructor() {
    this.authService = new AuthService();
  }

  login(username: string, password: string): boolean {
    return this.authService.login(username, password);
  }
}
