// Generated from the Blender material XfBAD__IW_0__m00_ by io_umvc3_css.
// Target ps_3_0; register assignments taken from the shader being replaced.
sampler2D tAlbedo : register(s0);

struct PSIn {
    float4 vcol : TEXCOORD0;   // .w carries the interpolated alpha
    float4 aux  : TEXCOORD1;
    float2 uv   : TEXCOORD2;
};

float4 main(PSIn psin) : COLOR
{
    float4 n_Image_Texture_Color_t = tex2D(tAlbedo, psin.uv);
    float3 n_Image_Texture_Color = n_Image_Texture_Color_t.rgb;
    float3 n_Invert_Color_Color = lerp(n_Image_Texture_Color, 1.0 - n_Image_Texture_Color, saturate(1.000000));
    return float4(n_Invert_Color_Color, psin.vcol.w);
}
