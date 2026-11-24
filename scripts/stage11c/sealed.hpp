#pragma once
#include <cerrno>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <sys/wait.h>
#include <unistd.h>
namespace c11 {
// Hash an already-open byte stream with the same coreutils executable used for the build lock.
inline std::string digest_fd(int fd) {
    int channel[2];if(pipe(channel))throw std::runtime_error("digest pipe");
    pid_t child=fork();
    if(child==0){
        if(dup2(fd,STDIN_FILENO)<0 || dup2(channel[1],STDOUT_FILENO)<0)_exit(126);
        close(channel[0]);close(channel[1]);execl("/usr/bin/sha256sum","sha256sum","-",static_cast<char*>(nullptr));_exit(127);
    }
    close(channel[1]);
    if(child<0){close(channel[0]);throw std::runtime_error("digest child");}
    char bytes[128];std::string response;
    for(;;){ssize_t n=read(channel[0],bytes,sizeof bytes);if(n>0)response.append(bytes,n);else if(n<0 && errno==EINTR)continue;else break;}
    close(channel[0]);int status=0;pid_t rc;do{rc=waitpid(child,&status,0);}while(rc<0 && errno==EINTR);
    if(rc!=child || !WIFEXITED(status) || WEXITSTATUS(status)!=0 || response.size()!=68 || response.substr(64)!="  -\n")throw std::runtime_error("digest command failed");
    return response.substr(0,64);
}
inline std::string digest_file(const std::string &path){
    FILE *f=fopen(path.c_str(),"rb");if(!f)throw std::runtime_error("missing sealed input");
    struct Close {FILE *f;~Close(){fclose(f);}} owner{f};return digest_fd(fileno(f));
}
inline std::string approved_stream(const std::string &dir) {
    std::string line;if(!std::getline(std::cin,line))throw std::runtime_error("missing private audit receipt");
    std::istringstream r(line);std::string version,input,graph,plan,extra;
    std::ifstream f(dir+"/approved.tsv",std::ios::binary|std::ios::ate);
    if(!f || f.tellg()<0 || f.tellg()>131072)throw std::runtime_error("invalid approved data length");
    std::string body(size_t(f.tellg()),'\0');f.seekg(0);
    if(!body.empty() && !f.read(&body[0],body.size()))throw std::runtime_error("short approved data");
    FILE *snapshot=tmpfile();if(!snapshot)throw std::runtime_error("approval snapshot");
    struct Close {FILE *p;~Close(){fclose(p);}} owned{snapshot};
    if(fwrite(body.data(),1,body.size(),snapshot)!=body.size() || fseek(snapshot,0,SEEK_SET))throw std::runtime_error("approval snapshot write");
    if(!(r>>version>>input>>graph>>plan) || version!="C11v1" || (r>>extra) ||
       input!=digest_file(dir+"/s8-input.bin") || graph!=digest_file(dir+"/s8-graph.tsv") ||
       plan!=digest_fd(fileno(snapshot)))throw std::runtime_error("private receipt / current input / approved clauses mismatch");
    return body;
}
}
