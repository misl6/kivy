$HEADER$
void main (void) {
  frag_color = clamp(color * vec4(1.0, 1.0, 1.0, opacity), 0.0, 1.0);
  tex_coord0 = vTexCoords0;
  gl_Position = projection_mat * modelview_mat * vec4(vPosition.xy, 0.0, 1.0);
}
